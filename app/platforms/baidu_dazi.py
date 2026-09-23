"""百度搭子（dumate，千帆控制台）：Cookie + 派生 csrftoken，每日登录奖励 +500。

协议源：agent_ext.rs L959-1065（生产验证）。
"""

from __future__ import annotations

import re
from typing import Any

from app.http import OpError, http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

DUMATE_BASE = 'https://console.bce.baidu.com'
DUMATE_DAILY_POINTS = 500

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36')

_AUTH_HINTS = ('login', '登录', 'csrf')


def derive_csrf(cookie: str) -> str:
    match = re.search(r'bce-user-info=([^;]*)', cookie)
    if not match:
        return ''
    return match.group(1).strip().strip('\\').strip('"').strip('\\')


def _headers(cookie: str) -> dict[str, str]:
    headers = {
        'Cookie': cookie,
        'Origin': DUMATE_BASE,
        'Referer': f'{DUMATE_BASE}/',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': BROWSER_UA,
    }
    csrf = derive_csrf(cookie)
    if csrf:
        headers['csrftoken'] = csrf
    return headers


def _unwrap(resp: Any) -> Any:
    """BCE 信封 {code,message,result}；登录迹象归一为 auth OpError。"""
    if not isinstance(resp, dict) or 'code' not in resp:
        raise OpError('Cookie 失效：响应缺少 code 字段（疑似登录页/重定向）', kind='auth')
    code = resp['code']
    if code in (0, 200):
        return resp.get('result')
    msg = str(resp.get('message') or '请求失败')
    if code in (302, 401, 403) or any(h in msg.lower() or h in msg for h in _AUTH_HINTS):
        raise OpError(f'Cookie 失效：code={code} {msg}', kind='auth')
    raise _BusinessError(f'code={code} {msg}')


class _BusinessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BaiduDaziAdapter(Adapter):
    platform = 'dazi'
    title = '百度搭子'
    credential_kind = 'cookie'

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        cookie = str(creds.get('cookie') or '').strip()
        if not cookie:
            raise OpError('缺少 Cookie', kind='auth')
        headers = _headers(cookie)
        try:
            try:
                info = _unwrap(http_json(
                    'GET', f'{DUMATE_BASE}/api/dumate/points/loginBonusInfo', headers))
            except _BusinessError as exc:
                return CheckinResult('error', f'查询签到状态失败：{exc.message}')
            info = info if isinstance(info, dict) else {}
            signed_days = len(info.get('signInDays') or [])
            if info.get('hasIssued'):
                return CheckinResult(
                    'already', f'今日已签到（本期已签 {signed_days} 天）')

            try:
                issued = _unwrap(http_json(
                    'POST', f'{DUMATE_BASE}/api/dumate/points/loginBonus',
                    headers, body={}))
            except _BusinessError as exc:
                return CheckinResult('error', f'领取失败：{exc.message}')
            if issued is False:
                return CheckinResult('already', '今日已签到')
            return CheckinResult(
                'ok', f'百度搭子签到成功 +{DUMATE_DAILY_POINTS} 积分',
                f'+{DUMATE_DAILY_POINTS} 积分')
        except OpError as exc:
            if exc.kind == 'parse':
                raise OpError(f'Cookie 失效：响应非 JSON（疑似重定向登录页）｜{exc}',
                              kind='auth') from None
            raise

    def credits(self, creds: dict[str, Any]) -> str | None:
        url = (f'{DUMATE_BASE}/api/dumate/points/quota_overview'
               '?timezone=Asia/Shanghai&clientType=desktop&ignoreLoginBonus=true')
        result = _unwrap(http_json('GET', url, _headers(str(creds.get('cookie') or ''))))
        top = (result or {}).get('totalPoints')
        if top:
            try:
                value = int(float(top)) - int(float(
                    (result or {}).get('usedPoints') or 0))
                return str(value) if value > 0 else None
            except (TypeError, ValueError):
                pass
        total = sum(int(i.get('totalPoints') or 0)
                    for i in (result or {}).get('subscription') or []
                    if isinstance(i, dict))
        return str(total) if total else None

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}


register(BaiduDaziAdapter())
