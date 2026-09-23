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


def run_all(platforms: list[str], *, store: Any, state: Any, config: Any,
            today: str, now_minutes: int,
            run_platform: Callable[[Any, dict, Any], CheckinResult]
            ) -> list[CheckinOutcome]:
    outcomes: list[CheckinOutcome] = []
    for platform in platforms:
        adapter = get_adapter(platform)
        if state.done_today(platform):
            result = _enrich(adapter, store.load(platform) or {},
                             CheckinResult('already', '今日已完成，跳过'),
                             state, platform, today)
            if result.balance:
                # 只回写余额：沿用原记录的状态/文案/奖励，空值不覆盖旧余额
                rec = state.get(platform, today) or {}
                state.mark(platform, CheckinResult(
                    rec.get('state', 'ok'), rec.get('message', ''),
                    rec.get('reward', ''), balance=result.balance,
                    streak=result.streak), today)
            outcomes.append(CheckinOutcome(platform, result))
            continue
        creds = store.load(platform)
        if not creds:
            outcomes.append(CheckinOutcome(
                platform, CheckinResult('error', f'未导入凭证（{adapter.title}）')))
            continue
        result = run_platform(adapter, creds, config)
        if result.done():
            state.mark(platform, result, today)   # 先落盘，streak 才含今天
            result = _enrich(adapter, creds, result, state, platform, today)
            state.mark(platform, result, today)   # 再落 enriched 值
        outcomes.append(CheckinOutcome(platform, result))
    return outcomes


def _write_balance(state: Any, adapter: Any, creds: dict,
                   platform: str, today: str) -> str | None:
    """查询余额并回写今日记录（仅当记录已存在；保留原状态/文案，不破坏幂等）。"""
    try:
        value = adapter.credits(creds)
    except Exception:
        return None
    if not value:
        return None
    rec = state.get(platform, today)
    if rec:
        state.mark(platform, CheckinResult(
            rec.get('state', 'ok'), rec.get('message', ''),
            rec.get('reward', ''), balance=str(value),
            streak=int(rec.get('streak') or 0)), today)
    return str(value)


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
        value = _write_balance(state, adapter, creds, platform, today)
        if value:
            out[platform] = value
    return out


def balance_due(now_ts: float, last_ts: float | None, minutes: int) -> bool:
    if last_ts is None or minutes <= 0:
        return False
    return (now_ts - last_ts) / 60 >= minutes
