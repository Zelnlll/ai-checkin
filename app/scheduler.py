"""每日调度：到点触发、当天已完成跳过、缺凭证报错。核心为纯函数便于测试。

多账号：每平台凭证为账号列表（id 缺省 'main'），逐账号签到并各存记录；
CheckinOutcome.result 为聚合结果（通知/卡片用），.accounts 为逐账号明细。
"""

from __future__ import annotations

import re
from collections import namedtuple
from dataclasses import replace
from typing import Any, Callable

from app.platforms import get_adapter
from app.platforms.base import CheckinResult

CheckinOutcome = namedtuple('CheckinOutcome', ['platform', 'result', 'accounts'],
                            defaults=({},))


def parse_num(text: str) -> float | None:
    m = re.search(r'-?[\d]+(?:[.][\d]+)?', str(text).replace(',', ''))
    return float(m.group()) if m else None


def fmt_num(v: float) -> str:
    v = round(v, 2)
    return str(int(v)) if v == int(v) else str(v)


def _accounts_of(store: Any, platform: str) -> list[dict[str, Any]]:
    load_all = getattr(store, 'load_all', None)
    if load_all:
        return load_all(platform)
    creds = store.load(platform)
    return [creds] if creds else []


def _acct_label(acct: dict[str, Any], index: int) -> str:
    return str(acct.get('label') or ('主账号' if index == 0 else f'账号{index + 1}'))


def _aggregate(platform_title: str,
               per: list[tuple[str, str, CheckinResult]]) -> CheckinResult:
    """per: [(acct_id, label, result)] → 平台聚合结果。"""
    results = [r for _, _, r in per]
    states = [r.state for r in results]
    rewards = [n for r in results if (n := parse_num(r.reward)) is not None]
    balances = [n for r in results if (n := parse_num(r.balance)) is not None]
    if all(s in ('ok', 'already') for s in states):
        state = 'ok' if any(s == 'ok' for s in states) else 'already'
        word = '全部完成'
    elif any(s == 'error' for s in states):
        state, word = 'error', '部分失败'
    else:
        state, word = 'busy', '待重试'
    fails = [f'{label}：{r.message}' for _, label, r in per if r.state == 'error']
    n_ok = sum(1 for s in states if s in ('ok', 'already'))
    if len(per) == 1:                      # 单账号：消息原样透传
        message = results[0].message
    else:
        message = (f'{n_ok}/{len(states)} 账号{word}'
                   + (f'（{"；".join(fails)[:120]}）' if fails else ''))
    reward = ''
    if len(per) == 1:
        reward = results[0].reward
    elif rewards:
        reward = f'+{fmt_num(sum(rewards))} 积分'
    balance = results[0].balance if len(per) == 1 else (
        fmt_num(sum(balances)) if balances else '')
    return CheckinResult(state, message, reward, balance, results[0].streak,
                         expiring=earliest_of([r.expiring for r in results]))


def _enrich(adapter: Any, creds: dict, result: CheckinResult,
            state: Any, platform: str, today: str,
            account: str = 'main') -> CheckinResult:
    streak = 0
    try:
        streak = state.streak(platform, today, account)
    except Exception:
        pass
    balance = ''
    try:
        value = adapter.credits(creds)
        if value:
            balance = str(value)
    except Exception:
        pass
    return replace(result, balance=balance, streak=streak)


def should_fire(now_minutes: int, checkin_time: tuple[int, int]) -> bool:
    return now_minutes >= checkin_time[0] * 60 + checkin_time[1]


def run_keepalive(store: Any, state: Any, platforms: list[str],
                  today: str) -> dict[str, bool]:
    """对已导入凭证的平台逐账号发一次轻量已认证请求续会话。"""
    results: dict[str, bool] = {}
    for platform in platforms:
        accounts = _accounts_of(store, platform)
        if not accounts:
            continue
        adapter = get_adapter(platform)
        ok_all = True
        for i, acct in enumerate(accounts):
            key = str(acct.get('id') or ('main' if i == 0 else f'acct{i + 1}'))
            ok = adapter.keepalive(acct)
            if ok:
                state.touch_keepalive(platform, today, key)
            else:
                ok_all = False
        results[platform] = ok_all
    return results


def _refresh_balance(state: Any, adapter: Any, creds: dict,
                     platform: str, today: str,
                     account: str = 'main') -> str | None:
    """查余额→只合并 balance（不碰 state/at，防伪造状态）→顺手打保活。"""
    try:
        value = adapter.credits(creds)
    except Exception:
        return None
    if not value:
        return None
    state.set_balance(platform, today, str(value), account)
    state.touch_keepalive(platform, today, account)
    return str(value)


def _streak(state: Any, platform: str, today: str,
            account: str = 'main') -> int:
    try:
        return state.streak(platform, today, account)
    except Exception:
        return 0


def _cache_expiring(state: Any, adapter: Any, creds: dict,
                    platform: str, today: str, account: str) -> str:
    """算最快到期积分→缓存进 state（set_expiring 只合并该字段）；失败返回 ''。"""
    exp = _earliest_expiring(adapter, creds) or ''
    if exp:
        state.set_expiring(platform, today, exp, account)
    return exp


def earliest_of(vals: list[str]) -> str:
    """多个 '100 · 09-30到期' 取日期最早；无值返回 ''。"""
    import re as _re

    def key(e: str) -> str:
        m = _re.search(r'·\s*([\d-]+)到期', e)
        return m.group(1) if m else '9999'
    got = [e for e in vals if e]
    return min(got, key=key) if got else ''


def run_all(platforms: list[str], *, store: Any, state: Any, config: Any,
            today: str, now_minutes: int,
            run_platform: Callable[[Any, dict, Any], CheckinResult]
            ) -> list[CheckinOutcome]:
    outcomes: list[CheckinOutcome] = []
    for platform in platforms:
        adapter = get_adapter(platform)
        accounts = _accounts_of(store, platform)
        if not accounts:
            result = CheckinResult('error', f'未导入凭证（{adapter.title}）')
            state.mark(platform, result, today)
            outcomes.append(CheckinOutcome(platform, result))
            continue
        per: list[tuple[str, str, CheckinResult]] = []
        for i, acct in enumerate(accounts):
            key = str(acct.get('id') or ('main' if i == 0 else f'acct{i + 1}'))
            label = _acct_label(acct, i)
            if state.done_today(platform, key):
                value = _refresh_balance(state, adapter, acct, platform,
                                         today, key)
                exp = _cache_expiring(state, adapter, acct, platform, today, key)
                per.append((key, label, CheckinResult(
                    'already', '今日已完成，跳过', balance=value or '',
                    streak=_streak(state, platform, today, key), expiring=exp)))
                continue
            result = run_platform(adapter, acct, config)
            state.mark(platform, result, today, key)   # 失败也落盘：面板可见原因
            if result.done():
                result = _enrich(adapter, acct, result, state, platform,
                                 today, key)
                state.mark(platform, result, today, key)   # 再落 enriched 值
            exp = _cache_expiring(state, adapter, acct, platform, today, key)
            if exp:
                result = replace(result, expiring=exp)
            per.append((key, label, result))
        agg = _aggregate(adapter.title, per)
        outcomes.append(CheckinOutcome(platform, agg,
                                       {k: r for k, _, r in per}))
    return outcomes


def _earliest_expiring(adapter: Any, creds: dict) -> str | None:
    """明细里最快过期的积分包：'100 · 10-01到期'；无明细/无过期项=None。"""
    try:
        rows = adapter.breakdown(creds) or []
    except Exception:                        # noqa: BLE001 —— 明细失败不影响余额轮
        return None
    for row in rows:                         # breakdown 已按失效时间升序
        exp = str(row.get('expire', ''))
        if '过期' not in exp:
            continue
        date = exp.split('（')[-1].rstrip('）') if '（' in exp else ''
        amount = row.get('amount', '')
        return f'{amount} · {date}到期' if date else f'{amount} 即将过期'
    return None


def run_balance(store: Any, state: Any, platforms: list[str],
                today: str) -> dict[str, str]:
    """余额循环刷新：逐账号只发 credits() 轻量 GET（兼作保活），不碰签到端点。"""
    out: dict[str, str] = {}
    for platform in platforms:
        accounts = _accounts_of(store, platform)
        if not accounts:
            continue
        try:
            adapter = get_adapter(platform)
        except Exception:
            continue
        values: list[str] = []
        for i, acct in enumerate(accounts):
            key = str(acct.get('id') or ('main' if i == 0 else f'acct{i + 1}'))
            value = _refresh_balance(state, adapter, acct, platform, today, key)
            if value:
                values.append(value)
            expiring = _earliest_expiring(adapter, acct)
            if expiring:
                state.set_expiring(platform, today, expiring, key)
        if len(values) == 1:
            out[platform] = values[0]
        elif values:
            nums = [n for n in (parse_num(v) for v in values) if n is not None]
            if nums:
                out[platform] = fmt_num(sum(nums))
    return out


def balance_due(now_ts: float, last_ts: float | None, minutes: int) -> bool:
    if last_ts is None or minutes <= 0:
        return False
    return (now_ts - last_ts) / 60 >= minutes
