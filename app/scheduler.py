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


def run_all(platforms: list[str], *, store: Any, state: Any, config: Any,
            today: str, now_minutes: int,
            run_platform: Callable[[Any, dict, Any], CheckinResult]
            ) -> list[CheckinOutcome]:
    outcomes: list[CheckinOutcome] = []
    for platform in platforms:
        adapter = get_adapter(platform)
        if state.done_today(platform):
            outcomes.append(CheckinOutcome(
                platform, _enrich(adapter, store.load(platform) or {},
                                  CheckinResult('already', '今日已完成，跳过'),
                                  state, platform, today)))
            continue
        creds = store.load(platform)
        if not creds:
            outcomes.append(CheckinOutcome(
                platform, CheckinResult('error', f'未导入凭证（{adapter.title}）')))
            continue
        result = run_platform(adapter, creds, config)
        if result.done():
            result = _enrich(adapter, creds, result, state, platform, today)
            state.mark(platform, result, today)   # 失败不落 done，留给重试
        outcomes.append(CheckinOutcome(platform, result))
    return outcomes
