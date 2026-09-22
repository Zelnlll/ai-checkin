"""CLI 入口：run-once / daemon / import / status / login。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import time
from typing import Callable

from app.config import Config, load_config
from app.credentials import CredentialStore
from app.notify import WeComNotifier
from app.platforms import ADAPTERS
from app.runner import run_platform
from app.scheduler import CheckinOutcome, run_all, should_fire
from app.state import DailyState

logger = logging.getLogger('ai-checkin')
TICK_SECONDS = 20


def due_to_run(now: dt.datetime, cfg: Config, last_run_date: str | None) -> bool:
    if last_run_date == now.date().isoformat():
        return False
    return should_fire(now.hour * 60 + now.minute, cfg.checkin_time)


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


def _last_run_date(state: DailyState) -> str | None:
    try:
        marker = state._file.parent / 'last_run.txt'
        return marker.read_text(encoding='utf-8').strip() if marker.exists() else None
    except Exception:
        return None


def _mark_run(state: DailyState) -> None:
    marker = state._file.parent / 'last_run.txt'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(dt.date.today().isoformat(), encoding='utf-8')


def cmd_daemon(cfg: Config) -> None:
    logger.info('守护模式启动：每日 %02d:%02d，重试 %d 次',
                *cfg.checkin_time, cfg.retry_times)
    state = DailyState(cfg.data_dir)
    while True:
        now = dt.datetime.now()
        if due_to_run(now, cfg, _last_run_date(state)):
            _mark_run(state)
            try:
                cmd_run_once(cfg)
            except Exception:
                logger.exception('本轮签到异常')
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
    p_web = sub.add_parser('web')
    p_web.add_argument('--port', type=int, default=8000)
    p_login = sub.add_parser('login')
    p_login.add_argument('platform')
    p_login.add_argument('--headful', action='store_true')
    args = parser.parse_args(argv)
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
