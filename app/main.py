"""CLI 入口：run-once / daemon / import / status / login。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable

from app.config import Config, load_config
from app.credentials import CredentialStore
from app.notify import WeComNotifier
from app.platforms import ADAPTERS
from app.runner import run_platform
from app.scheduler import CheckinOutcome, balance_due, run_all, should_fire
from app.state import DailyState

logger = logging.getLogger('ai-checkin')
TICK_SECONDS = 20


MAX_ROUNDS = 6
RETRY_GAP_MINUTES = 30


def due_to_run(now: dt.datetime, cfg: Config, marker: str | None) -> bool:
    """marker：'YYYY-MM-DD'（旧格式=done）| '... done' | '... <轮次> <HH:MM>'。"""
    if not should_fire(now.hour * 60 + now.minute, cfg.checkin_time):
        return False
    if not marker:
        return True
    parts = marker.split()
    if parts[0] != now.date().isoformat():
        return True
    if len(parts) == 1 or parts[1] == 'done':
        return False
    if not parts[1].isdigit() or int(parts[1]) >= MAX_ROUNDS:
        return False
    try:
        hh, mm = map(int, parts[2].split(':'))
        last = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except (IndexError, ValueError):
        return False
    return now >= last + dt.timedelta(minutes=RETRY_GAP_MINUTES)


def next_marker(now: dt.datetime, marker: str | None,
                outcomes: list | None) -> str:
    today = now.date().isoformat()
    rounds = 0
    if marker:
        parts = marker.split()
        if parts[0] == today and len(parts) > 1 and parts[1].isdigit():
            rounds = int(parts[1])
    if outcomes is not None and all(o.result.done() for o in outcomes):
        return f'{today} done'
    return f'{today} {rounds + 1} ' + now.strftime('%H:%M')


def _default_runner(cfg: Config):
    log_path = cfg.data_dir / 'logs' / 'requests.log'

    def runner(adapter, creds, config):
        return run_platform(adapter, creds, retry_times=cfg.retry_times,
                            log_path=log_path)
    return runner


def choose_notifier(cfg: Config):
    from app.notify_app import make_notifier
    return make_notifier(cfg)


def cmd_run_once(cfg: Config, *, platforms: list[str] | None = None,
                 store: CredentialStore | None = None,
                 state: DailyState | None = None,
                 notifier: WeComNotifier | None = None,
                 runner_fn: Callable | None = None) -> list[CheckinOutcome]:
    platforms = platforms or list(ADAPTERS)
    store = store or CredentialStore(cfg.data_dir, set(ADAPTERS))
    state = state or DailyState(cfg.data_dir)
    notifier = notifier or choose_notifier(cfg)
    runner_fn = runner_fn or _default_runner(cfg)
    try:
        from app.scanner import scan_local_accounts
        scan_local_accounts(cfg.data_dir / 'inbox')
    except Exception:
        pass
    imported = store.import_inbox()
    if imported:
        logger.info('inbox 导入凭证：%s', imported)
    now = dt.datetime.now()
    outcomes = run_all(platforms, store=store, state=state, config=cfg,
                       today=now.date().isoformat(),
                       now_minutes=now.hour * 60 + now.minute,
                       run_platform=runner_fn)
    notifier.push(outcomes, now.date().isoformat())
    return outcomes


class _NoopNotifier:
    def push(self, outcomes, today):
        return True


def outcomes_signature(outcomes: list[CheckinOutcome]) -> str:
    return ';'.join(sorted(f'{o.platform}:{o.result.state}' for o in outcomes))


def _push_if_changed(cfg: Config, outcomes: list[CheckinOutcome]) -> bool:
    """状态签名与上次已推送不同才发卡（首轮必发、全成功必发、重复状态静默）。"""
    today = dt.date.today().isoformat()
    sig = f'{today} ' + outcomes_signature(outcomes)   # 带日期：隔天同签名照发
    f = cfg.data_dir / 'last_push_sig.txt'
    try:
        last = f.read_text(encoding='utf-8').strip() if f.exists() else None
    except Exception:
        last = None
    if last == sig:
        logger.info('状态无变化，跳过推送：%s', sig)
        return False
    choose_notifier(cfg).push(outcomes, today)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.txt.tmp')
    tmp.write_text(sig, encoding='utf-8')
    tmp.replace(f)
    return True


def _marker_file(state: DailyState) -> Path:
    return state._file.parent / 'last_run.txt'


def _read_marker(state: DailyState) -> str | None:
    try:
        f = _marker_file(state)
        return f.read_text(encoding='utf-8').strip() if f.exists() else None
    except Exception:
        return None


def _write_marker(state: DailyState, content: str) -> None:
    f = _marker_file(state)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix('.txt.tmp')
    tmp.write_text(content, encoding='utf-8')
    tmp.replace(f)


def _start_panel(cfg: Config, port: int):
    """同进程起面板 HTTP 服务（守护线程），返回 httpd 便于测试/关停。"""
    from app.webapp import serve_app
    httpd = serve_app(cfg, port)
    threading.Thread(target=httpd.serve_forever, daemon=True,
                     name='panel').start()
    return httpd


def cmd_daemon(cfg: Config) -> None:
    logger.info('守护模式启动：每日 %02d:%02d，重试 %d 次，余额每 %d 分钟刷新',
                *cfg.checkin_time, cfg.retry_times, cfg.balance_refresh_minutes)
    raw_port = (os.environ.get('PANEL_PORT') or '').strip()
    panel_port = int(raw_port) if raw_port.isdigit() else 8000
    try:
        _start_panel(cfg, panel_port)
        logger.info('面板已随守护启动：http://0.0.0.0:%d', panel_port)
    except OSError as exc:
        logger.error('面板端口 %d 占用，仅运行守护： %s', panel_port, exc)
    state = DailyState(cfg.data_dir)
    last_balance_ts: float = 0.0   # 启动后首轮 tick 即刷新一次已有记录的余额
    while True:
        now = dt.datetime.now()
        if balance_due(time.time(), last_balance_ts, cfg.balance_refresh_minutes):
            last_balance_ts = time.time()
            try:
                from app.scheduler import run_balance
                store = CredentialStore(cfg.data_dir, set(ADAPTERS))
                balances = run_balance(store, DailyState(cfg.data_dir),
                                       list(ADAPTERS), dt.date.today().isoformat())
                if balances:
                    logger.info('余额刷新：%s', balances)
            except Exception:
                logger.exception('余额刷新异常')
        marker = _read_marker(state)
        if due_to_run(now, cfg, marker):
            try:
                outcomes = cmd_run_once(cfg, notifier=_NoopNotifier())
                _push_if_changed(cfg, outcomes)
            except Exception:
                logger.exception('本轮签到异常')
                outcomes = None
            _write_marker(state, next_marker(now, marker, outcomes))
            try:
                from app.scheduler import run_keepalive
                store = CredentialStore(cfg.data_dir, set(ADAPTERS))
                results = run_keepalive(store, DailyState(cfg.data_dir),
                                        list(ADAPTERS), dt.date.today().isoformat())
                logger.info('保活结果：%s', results)
            except Exception:
                logger.exception('保活异常')
        time.sleep(TICK_SECONDS)


def cmd_status(cfg: Config) -> None:
    store = CredentialStore(cfg.data_dir, set(ADAPTERS))
    state = DailyState(cfg.data_dir)
    today = dt.date.today().isoformat()
    for platform, adapter in ADAPTERS.items():
        creds = store.load(platform)
        cred_info = '未导入' if not creds else (
            f"已导入（{creds.get('saved_at', '?')}）")
        if creds:
            report = store.expiry_report(platform, creds, adapter)
            if report.get('expired') or report.get('likely_expired_soon'):
                cred_info += ' ⚠ 凭证临期/失效'
        rec = state.get(platform, today)
        day = f"{rec['state']} {rec['message']}" if rec else '今日未执行'
        print(f'{adapter.title:12} 凭证：{cred_info:40} 今日：{day}')


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    parser = argparse.ArgumentParser(prog='ai-checkin')
    sub = parser.add_subparsers(dest='command', required=True)
    p_once = sub.add_parser('run-once')
    p_once.add_argument('platforms', nargs='*')
    sub.add_parser('daemon')
    sub.add_parser('import')
    sub.add_parser('scan')
    sub.add_parser('keepalive')
    sub.add_parser('status')
    sub.add_parser('version')
    p_web = sub.add_parser('web')
    p_web.add_argument('--port', type=int, default=8000)
    p_login = sub.add_parser('login')
    p_login.add_argument('platform')
    p_login.add_argument('--headful', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'version':
        from app import __version__
        print(f'ai-checkin v{__version__}')
        return 0
    cfg = load_config()
    if args.command == 'run-once':
        outcomes = cmd_run_once(cfg, platforms=args.platforms or None)
        for o in outcomes:
            print(f'{o.platform}: {o.result.state} {o.result.message}')
    elif args.command == 'daemon':
        cmd_daemon(cfg)
    elif args.command == 'import':
        store = CredentialStore(cfg.data_dir, set(ADAPTERS))
        print(store.import_inbox() or 'inbox 无新凭证')
    elif args.command == 'scan':
        from app.scanner import scan_local_accounts
        found = scan_local_accounts(cfg.data_dir / 'inbox')
        store = CredentialStore(cfg.data_dir, set(ADAPTERS))
        store.import_inbox()
        print('已导入：' + '、'.join(found) if found else '未发现可导入账号')
    elif args.command == 'keepalive':
        from app.scheduler import run_keepalive
        store = CredentialStore(cfg.data_dir, set(ADAPTERS))
        results = run_keepalive(store, DailyState(cfg.data_dir),
                                list(ADAPTERS), dt.date.today().isoformat())
        print(results or '无已导入凭证的平台')
    elif args.command == 'status':
        cmd_status(cfg)
    elif args.command == 'web':
        from app.webapp import serve
        serve(cfg, args.port)
    elif args.command == 'login':
        from app.browser_login import browser_login  # playwright 仅此处依赖
        return browser_login(cfg, args.platform, headful=args.headful)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
