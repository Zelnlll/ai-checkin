"""WorkBuddy（copilot.tencent.com）每日签到：桌面端会话 accessToken + uid 直调。

协议源：GitHub Minatoxiaohu/agent-auto-signin workbuddy_signin.py（成长中心全家桶
中只取最小签到两接口）。响应契约：领取成功含 credit；已签=null/400 code10001。
凭证来源：PC 扫描 %LOCALAPPDATA%\\CodeBuddyExtension\\...\\workbuddy-desktop.info。
"""

from __future__ import annotations

from typing import Any

from app.http import http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

WB_ENDPOINT = 'https://copilot.tencent.com'
STATUS_PATH = '/v2/billing/meter/checkin-activity-status'
CLAIM_PATH = '/v2/billing/meter/daily-checkin'


def _dig(obj: Any, key: str) -> Any:
    """在可能被 data/result 包裹的响应里找字段（社区同款信封兼容）。"""
    if isinstance(obj, dict):
        if obj.get(key) is not None:
            return obj[key]
        for wrap in ('data', 'result'):
            inner = obj.get(wrap)
            if isinstance(inner, dict):
                val = _dig(inner, key)
                if val is not None:
                    return val
    return None


class WorkbuddyAdapter(Adapter):
    platform = 'workbuddy'
    title = 'WorkBuddy'
    credential_kind = 'token'

    def _post(self, creds: dict[str, Any], path: str) -> Any:
        token = str(creds.get('token') or '').strip()
        if not token:
            from app.http import OpError
            raise OpError('缺少 accessToken', kind='auth')
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'X-User-Id': str(creds.get('uid') or ''),
            'User-Agent': 'WorkBuddy',
        }
        if creds.get('enterprise_id'):
            headers['X-Enterprise-Id'] = str(creds['enterprise_id'])
            headers['X-Tenant-Id'] = str(creds['enterprise_id'])
        if creds.get('domain'):
            headers['X-Domain'] = str(creds['domain'])
        endpoint = str(creds.get('endpoint') or WB_ENDPOINT).rstrip('/')
        return http_json('POST', endpoint + path, headers)

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        st = self._post(creds, STATUS_PATH)
        if _dig(st, 'today_checked_in') in (True, 1):
            total = _dig(st, 'total_credits')
            tail = f'（余 {total}）' if total else ''
            return CheckinResult('already', f'今日已签到{tail}')
        try:
            cl = self._post(creds, CLAIM_PATH)
        except Exception as exc:      # noqa: BLE001 —— 400 code10001 走"已签"判定
            from app.http import OpError
            text = str(exc)
            if '10001' in text or '已签到' in text:
                return CheckinResult('already', '今日已签到（服务端判定）')
            if isinstance(exc, OpError) and exc.kind == 'http':
                return CheckinResult('error', text[:120])
            if isinstance(exc, OpError) and exc.kind == 'parse' \
                    and text.rstrip().endswith('null'):
                return CheckinResult('already', '今日已签到（空响应幂等）')
            raise
        credit = _dig(cl, 'credit')
        if credit is not None:
            st2 = self._post(creds, STATUS_PATH)
            total = _dig(st2, 'total_credits') or _dig(st, 'total_credits')
            return CheckinResult('ok',
                                 f'WorkBuddy 签到成功 +{credit} 积分'
                                 + (f'（余 {total}）' if total else ''),
                                 f'+{credit} 积分')
        code = _dig(cl, 'code')
        msg = _dig(cl, 'msg') or _dig(cl, 'message') or ''
        return CheckinResult('error', f'领取失败 code={code} {msg}'
                             if code is not None or msg else
                             f'领取失败：响应缺少 credit {str(cl)[:100]}')

    def credits(self, creds: dict[str, Any]) -> str | None:
        st = self._post(creds, STATUS_PATH)
        total = _dig(st, 'total_credits')
        return str(total) if total else None


register(WorkbuddyAdapter())
