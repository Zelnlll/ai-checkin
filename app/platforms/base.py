"""适配器基类与统一签到结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_STATES = ('ok', 'already', 'busy', 'error')


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

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
