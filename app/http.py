"""HTTP 与 JWT 小工具（移植自 agent_checkin/adapters.py，行为对齐）。"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any


class OpError(RuntimeError):
    def __init__(self, message: str, *, kind: str = 'error',
                 http_status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status


def _try_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def http_json(method: str, url: str, headers: dict[str, str],
              body: Any = None, timeout: int = 25) -> Any:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode('utf-8', 'replace')
        except Exception:
            raw = ''
        status = exc.code
        payload = _try_json(raw)
        if isinstance(payload, dict):
            msg = str(payload.get('message') or payload.get('msg')
                      or payload.get('error') or raw[:120])
        else:
            msg = raw[:120] or f'HTTP {status}'
        raise OpError(f'HTTP {status}：{msg}',
                      kind='auth' if status in (401, 403) else 'http',
                      http_status=status) from None
    except urllib.error.URLError as exc:
        raise OpError(f'网络不通：{getattr(exc, "reason", exc)}', kind='network') from None
    except (TimeoutError, OSError) as exc:
        raise OpError(f'网络异常：{exc}', kind='network') from None

    payload = _try_json(raw)
    if payload is None:
        raise OpError(f'响应无法解析：{raw[:120]}', kind='parse')
    return payload


def jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = token.split('.')
        if len(parts) < 2:
            return {}
        seg = parts[1]
        seg += '=' * (-len(seg) % 4)
        payload = json.loads(base64.urlsafe_b64decode(seg.encode('ascii')))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def jwt_exp_s(token: str) -> int:
    exp = jwt_payload(token).get('exp')
    try:
        return int(exp) if exp else 0
    except (TypeError, ValueError):
        return 0


def jwt_sub(token: str) -> str:
    return str(jwt_payload(token).get('sub') or '')
