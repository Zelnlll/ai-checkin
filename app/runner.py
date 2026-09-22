"""单平台执行器：重试/指数退避/auth 即停/请求日志。"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Callable

from app.http import OpError
from app.platforms.base import Adapter, CheckinResult

BASE_BACKOFF_SECONDS = 10


def _log_attempt(log_path: Path | None, platform: str, state: str, message: str) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        'time': dt.datetime.now().isoformat(timespec='seconds'),
        'platform': platform, 'state': state, 'message': message[:300],
    }, ensure_ascii=False)
    with log_path.open('a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def run_platform(adapter: Adapter, creds: dict[str, Any], *,
                 retry_times: int, sleep: Callable[[float], None] = time.sleep,
                 log_path: Path | None = None) -> CheckinResult:
    last = CheckinResult('error', '未执行')
    for attempt in range(retry_times + 1):
        try:
            result = adapter.checkin(creds)
        except OpError as exc:
            if exc.kind == 'auth':
                _log_attempt(log_path, adapter.platform, 'auth', str(exc))
                return CheckinResult('error', f'凭证失效：{exc}')
            last = CheckinResult('error', str(exc))
            _log_attempt(log_path, adapter.platform, last.state, str(exc))
        except Exception as exc:
            last = CheckinResult('error', f'{type(exc).__name__}: {exc}')
            _log_attempt(log_path, adapter.platform, last.state, last.message)
        else:
            _log_attempt(log_path, adapter.platform, result.state, result.message)
            if result.state in ('ok', 'already'):
                return result
            last = result
        if attempt < retry_times:
            sleep(BASE_BACKOFF_SECONDS * (2 ** attempt))
    return last
