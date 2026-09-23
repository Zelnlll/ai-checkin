"""环境变量 → 类型化配置。非法值回退默认或拒绝，取决于是否会静默改变行为。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHECKIN_TIME = (10, 5)
DEFAULT_RETRY_TIMES = 3


@dataclass(frozen=True)
class Config:
    checkin_time: tuple[int, int]
    retry_times: int
    wecom_webhook: str
    data_dir: Path
    wecom_corp_id: str = ''
    wecom_corp_secret: str = ''
    wecom_agent_id: int = 0
    wecom_to_user: str = ''
    wecom_chat_id: str = ''
    wecom_api_base: str = 'https://qyapi.weixin.qq.com/cgi-bin'
    balance_refresh_minutes: int = 60


def _parse_checkin_time(raw: str) -> tuple[int, int]:
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', raw.strip())
    if not match:
        return DEFAULT_CHECKIN_TIME
    hh, mm = int(match.group(1)), int(match.group(2))
    if hh > 23 or mm > 59:
        return DEFAULT_CHECKIN_TIME
    return hh, mm


def _parse_int(raw: str) -> int:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else 0


def load_config(env: dict[str, str] | None = None) -> Config:
    source = os.environ if env is None else env
    raw_retry = source.get('RETRY_TIMES', '').strip() or str(DEFAULT_RETRY_TIMES)
    if not raw_retry.isdigit():
        raise ValueError(f'RETRY_TIMES 必须是数字，当前值：{raw_retry!r}')
    retry_times = int(raw_retry)
    if retry_times < 0:
        raise ValueError(f'RETRY_TIMES 不能为负，当前值：{retry_times}')
    return Config(
        checkin_time=_parse_checkin_time(source.get('CHECKIN_TIME', '')),
        retry_times=retry_times,
        wecom_webhook=source.get('WECOM_WEBHOOK', '').strip(),
        data_dir=Path(source.get('DATA_DIR', '/data')),
        wecom_corp_id=source.get('WECOM_CORP_ID', '').strip(),
        wecom_corp_secret=source.get('WECOM_CORP_SECRET', '').strip(),
        wecom_agent_id=_parse_int(source.get('WECOM_AGENT_ID', '')),
        wecom_to_user=source.get('WECOM_TO_USER', '').strip(),
        wecom_chat_id=source.get('WECOM_CHAT_ID', '').strip(),
        wecom_api_base=source.get('WECOM_API_BASE', '').strip()
        or 'https://qyapi.weixin.qq.com/cgi-bin',
        balance_refresh_minutes=_parse_int(
            source.get('BALANCE_REFRESH_MINUTES', '')) or 60,
    )
