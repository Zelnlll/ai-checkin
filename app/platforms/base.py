"""适配器基类与统一签到结果模型。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

VALID_STATES = ('ok', 'already', 'busy', 'error')


def expire_text(ts_seconds: float) -> str:
    d = dt.date.fromtimestamp(ts_seconds)
    n = (d - dt.date.today()).days
    return ('今日过期' if n <= 0 else f'{n}天后过期') + f'（{d:%m-%d}）'


def fmt_amount(value: float) -> str:
    v = round(value, 2)
    return str(int(v)) if v == int(v) else str(v)


@dataclass(frozen=True)
class CheckinResult:
    state: str
    message: str
    reward: str = ''
    balance: str = ''
    streak: int = 0

    def __post_init__(self):
        if self.state not in VALID_STATES:
            raise ValueError(f'未知状态：{self.state!r}，应为 {VALID_STATES}')

    def done(self) -> bool:
        return self.state in ('ok', 'already')


class Adapter:
    platform: str = ''
    title: str = ''
    credential_kind: str = 'token'  # cookie | token

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        raise NotImplementedError

    def credits(self, creds: dict[str, Any]) -> str | None:
        """可选：返回可用余额展示串（如 '2592'），None=不支持。"""
        return None

    def breakdown(self, creds: dict[str, Any]) -> list[dict[str, str]] | None:
        """可选：积分明细 [{'tag','name','amount','expire'}]，None=官方无此接口。"""
        return None

    def keepalive(self, creds: dict[str, Any]) -> bool:
        """轻量已认证请求续会话；默认借道 credits 查询（拿不到数=没续上）。"""
        try:
            return self.credits(creds) is not None
        except Exception:
            return False

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
