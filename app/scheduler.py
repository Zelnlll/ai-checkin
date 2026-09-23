"""每日调度：到点触发、当天已完成跳过、缺凭证报错。核心为纯函数便于测试。"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import replace
from typing import Any, Callable

from app.platforms import get_adapter
from app.platforms.base import CheckinResult

CheckinOutcome = namedtuple('CheckinOutcome', ['platform', 'result'])


def _enrich(adapter: Any, creds: dict, result: CheckinResult,
            state: Any, platform: str, today: str) -> CheckinResult:
    streak = 0
    try:
        streak = state.streak(platform, today)
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
    """对已导入凭证的平台发一次轻量已认证请求续会话，成功则记保活日期。"""
    results: dict[str, bool] = {}
    for platform in platforms:
        creds = store.load(platform)
        if not creds:
            continue
        ok = get_adapter(platform).keepalive(creds)
        if ok:
            state.touch_keepalive(platform, today)
        results[platform] = bool(ok)
    return results


def _refresh_balance(state: Any, adapter: Any, creds: dict,
                     platform: str, today: str) -> str | None:
    """查余额→只合并 balance（不碰 state/at，防伪造状态）→顺手打保活。"""
    try:
        value = adapter.credits(creds)
    except Exception:
        return None
    if not value:
        return None
    state.set_balance(platform, today, str(value))
    state.touch_keepalive(platform, today)
    return str(value)


def _streak(state: Any, platform: str, today: str) -> int:
    try:
        return state.streak(platform, today)
    except Exception:
        return 0


def run_all(platforms: list[str], *, store: Any, state: Any, config: Any,
            today: str, now_minutes: int,
            run_platform: Callable[[Any, dict, Any], CheckinResult]
            ) -> list[CheckinOutcome]:
    outcomes: list[CheckinOutcome] = []
    for platform in platforms:
        adapter = get_adapter(platform)
        creds = store.load(platform) or {}
        if state.done_today(platform):
            value = _refresh_balance(state, adapter, creds, platform, today)
            outcomes.append(CheckinOutcome(platform, CheckinResult(
                'already', '今日已完成，跳过', balance=value or '',
                streak=_streak(state, platform, today))))
            continue
        if not creds:
            result = CheckinResult('error', f'未导入凭证（{adapter.title}）')
            state.mark(platform, result, today)
            outcomes.append(CheckinOutcome(platform, result))
            continue
        result = run_platform(adapter, creds, config)
        state.mark(platform, result, today)   # 失败也落盘：面板可见原因
        if result.done():
            result = _enrich(adapter, creds, result, state, platform, today)
            state.mark(platform, result, today)   # 再落 enriched 值
        outcomes.append(CheckinOutcome(platform, result))
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
    """余额循环刷新：只发各平台 credits() 轻量 GET（兼作保活），不碰签到端点。"""
    out: dict[str, str] = {}
    for platform in platforms:
        creds = store.load(platform)
        if not creds:
            continue
        try:
            adapter = get_adapter(platform)
        except Exception:
            continue
        value = _refresh_balance(state, adapter, creds, platform, today)
        if value:
            out[platform] = value
        expiring = _earliest_expiring(adapter, creds)
        if expiring:
            state.set_expiring(platform, today, expiring)
    return out


def balance_due(now_ts: float, last_ts: float | None, minutes: int) -> bool:
    if last_ts is None or minutes <= 0:
        return False
    return (now_ts - last_ts) / 60 >= minutes
