"""TraeWork（api.trae.cn）每日签到：桌面端 storage token + Cloud-IDE-JWT 直调。

协议源：GitHub Minatoxiaohu/agent-auto-signin trae_signin.py（2026-09 交叉验证），
本机 2026-09-23 实测 status/claim 直调可行（wb-switch 的 9074 记录针对网页
Cloud-IDE-Token，桌面 storage token 不受限）。每日 200 积分，按设备计一次。
"""

from __future__ import annotations

from typing import Any

from app.http import http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

TRAE_HOST = 'https://api.trae.cn'
STATUS_PATH = '/trae/api/v2/ug/checkin_credits/status'
CLAIM_PATH = '/trae/api/v2/ug/checkin_credits/claim'


class TraeAdapter(Adapter):
    platform = 'trae'
    title = 'TraeWork'
    credential_kind = 'token'

    def _post(self, creds: dict[str, Any], path: str) -> Any:
        token = str(creds.get('token') or '').strip()
        if not token:
            from app.http import OpError
            raise OpError('缺少 token', kind='auth')
        headers = {
            'Authorization': f'Cloud-IDE-JWT {token}',
            'X-User-Region': str(creds.get('region') or 'CN'),
            'Content-Type': 'application/json',
        }
        if creds.get('device_id'):
            headers['X-Device-Id'] = str(creds['device_id'])
        host = str(creds.get('host') or TRAE_HOST).rstrip('/')
        return http_json('POST', host + path, headers, body={})

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        st = self._post(creds, STATUS_PATH)
        if not isinstance(st, dict) or not st.get('enable'):
            return CheckinResult('error', 'TraeWork 签到活动未开启')
        credits = st.get('credits')
        if st.get('checked_in'):
            return CheckinResult('already', f'今日已签到（+{credits} 积分）')
        cl = self._post(creds, CLAIM_PATH)
        body = cl if isinstance(cl, dict) else {}
        if body.get('code') == 0:
            data = body.get('data') if isinstance(body.get('data'), dict) else {}
            got = data.get('credits') or credits or 200
            return CheckinResult('ok', f'TraeWork 签到成功 +{got} 积分',
                                 f'+{got} 积分')
        if body.get('code') == 9004:
            # 名额已被本账号其他设备/网页领取（status 与 claim 间的竞态窗口）
            return CheckinResult('already', '今日已签到（服务端判定已领取）')
        return CheckinResult('error',
                             f"领取失败 code={body.get('code')} {body.get('message', '')}")

    def credits(self, creds: dict[str, Any]) -> str | None:
        st = self._post(creds, STATUS_PATH)
        value = (st or {}).get('credits') if isinstance(st, dict) else None
        return str(value) if value else None


register(TraeAdapter())
