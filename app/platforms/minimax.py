"""MiniMax Code（agent.minimaxi.com）：JWT + 官方客户端双 MD5 盐签名。

协议源：agent_ext.rs L1124-1240（生产验证）。盐为客户端硬编码常量，非用户密钥。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any
from urllib.parse import quote

from app.http import OpError, http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

MINIMAX_BASE = 'https://agent.minimaxi.com'
MINIMAX_BASE_ALT = 'https://agent.minimax.io'

SIGN_SALT = 'I*7Cf%WZ#S&%1RlZJ&C2'
YY_SALT = 'ooui'

AUTH_STATUS_CODES = (1022100011,)
BUSY_HINTS = ('拥挤', '繁忙', '稍后', 'later')

STATUS_PATH = '/minimax-cloud/api/v1/signin/status?timezone_id=Asia/Shanghai'
CLAIM_PATH = '/minimax-cloud/api/v1/signin/claim'


def _md5(raw: str) -> str:
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


_JS_UNRESERVED = "-_.!~*'()"   # encodeURIComponent 不转义的符号集


def minimax_headers(token: str, path_with_query: str, body_str: str,
                    ts: str | None = None, ms: str | None = None) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    ms = ms or str(int(time.time() * 1000))
    yy_body = body_str if body_str else '{}'
    return {
        'token': token,
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MiniMaxCode',
        'x-timestamp': ts,
        'x-signature': _md5(f'{ts}{SIGN_SALT}{body_str}'),
        'yy': _md5(quote(path_with_query, safe=_JS_UNRESERVED) + f'_{yy_body}'
                  + _md5(ms) + YY_SALT),
    }


def _request(path_with_query: str, body: dict | None, token: str) -> Any:
    body_str = json.dumps(body, ensure_ascii=False) if body is not None else ''
    method = 'POST' if body is not None else 'GET'
    last_exc: Exception | None = None
    for base in (MINIMAX_BASE, MINIMAX_BASE_ALT):
        headers = minimax_headers(token, path_with_query, body_str)
        try:
            payload = http_json(method, f'{base}{path_with_query}', headers,
                                body=body if body is not None else None)
        except OpError as exc:
            if exc.kind in ('network', 'parse'):
                last_exc = exc
                continue           # 传输层失败 → 回落备用域名
            raise
        if isinstance(payload, dict) and ('base_resp' in payload or 'data' in payload):
            return payload
        last_exc = OpError(f'响应缺少信封：{str(payload)[:120]}', kind='parse')
    raise last_exc if last_exc else OpError('请求失败', kind='network')


def _unwrap(resp: Any) -> dict[str, Any]:
    base = resp.get('base_resp') if isinstance(resp, dict) else None
    code = int((base or {}).get('status_code') or (resp or {}).get('code') or 0)
    msg = str((base or {}).get('status_msg') or (resp or {}).get('message') or '请求失败')
    if code == 0:
        data = resp.get('data')
        # credit/details 等接口无 data 包裹，字段直接在顶层
        return data if isinstance(data, dict) else resp
    if code in AUTH_STATUS_CODES:
        raise OpError(f'status_code={code} {msg}（token 失效：重开 MiniMax 客户端或重新粘贴）',
                      kind='auth')
    raise _BusinessError(f'status_code={code} {msg}')


class _BusinessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class MinimaxAdapter(Adapter):
    platform = 'minimax'
    title = 'MiniMax Code'
    credential_kind = 'token'

    @staticmethod
    def _call(creds: dict[str, Any], path: str, body: dict | None) -> Any:
        token = str(creds.get('token') or '').strip()
        if creds.get('web_session'):
            from app import minimax_web
            return minimax_web.web_request(path, body, token,
                                           str(creds.get('user_id') or ''))
        return _request(path, body, token)

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        token = str(creds.get('token') or '').strip()
        if not token:
            raise OpError('缺少 token', kind='auth')
        try:
            try:
                data = _unwrap(self._call(creds, STATUS_PATH, None))
            except _BusinessError as exc:
                return CheckinResult('error', f'查询签到状态失败：{exc.message}')
            today = next((d for d in data.get('days') or []
                          if isinstance(d, dict) and d.get('is_today')), None)
            points = int((today or {}).get('points') or 0)
            if today and int(today.get('status') or 0) == 3:
                return CheckinResult('already', f'今日已签到（+{points} 积分）')
            try:
                claimed = _unwrap(self._call(creds, CLAIM_PATH, {}))
            except _BusinessError as exc:
                if any(h in exc.message for h in BUSY_HINTS):
                    return CheckinResult('busy', f'服务器拥挤，稍后自动重试：{exc.message}')
                return CheckinResult('error', exc.message)
            result = int(claimed.get('claim_result') or claimed.get('claimResult') or 0)
            gained = int(claimed.get('points') or points or 0)
            if result == 1:
                return CheckinResult('ok', f'MiniMax 签到成功 +{gained} 积分',
                                     f'+{gained} 积分')
            return CheckinResult('already', '今日已签到')   # 官方幂等兜底
        except OpError as exc:
            if exc.kind == 'parse':
                raise OpError(f'token 失效或签名异常：{exc}', kind='auth') from None
            raise

    def credits(self, creds: dict[str, Any]) -> str | None:
        data = _unwrap(self._call(
            creds, '/minimax-cloud/api/v1/credit/details?timezone_id=Asia/Shanghai',
            None))
        today = dt.date.today().isoformat()
        total = 0.0
        for item in data.get('details') or []:
            if not isinstance(item, dict):
                continue
            exp_ms = item.get('expire_at_ms')
            if exp_ms is not None:
                try:
                    if float(exp_ms) / 1000 < time.time():
                        continue
                except (TypeError, ValueError):
                    continue
            else:
                expire = str(item.get('expire_time') or item.get('expire_at') or '')
                if expire and expire[:10] < today:
                    continue
            raw = item.get('remaining_amount')
            if raw is None:
                raw = item.get('remain')
            if raw is None:
                raw = item.get('amount')
            try:
                total += float(raw or 0)
            except (TypeError, ValueError):
                continue
        if not total:
            return None
        return str(int(total)) if total == int(total) else str(round(total, 1))

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        from app.http import jwt_exp_s
        exp = jwt_exp_s(str(creds.get('token') or ''))
        if not exp:
            return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
        left = exp - time.time()
        return {'known': True, 'expired': left <= 0,
                'expires_at': dt.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M'),
                'days_left': round(left / 86400, 1)}


register(MinimaxAdapter())
