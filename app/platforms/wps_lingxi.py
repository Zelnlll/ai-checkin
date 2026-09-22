"""WPS 灵犀（lingxi.kdocs.cn）：Cookie 鉴权，daily_check_in 任务领取。

协议源：agent_ext.rs L1291-1420 + checkin-capture/wps.json 真实样本。
"""

from __future__ import annotations

from typing import Any

from app.http import OpError, http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

WPS_BASE = 'https://lingxi.kdocs.cn'

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36')

CLAIMED_WORDS = ('claimed', 'done', 'finished', 'received')


def _headers(cookie: str) -> dict[str, str]:
    return {
        'Cookie': cookie,
        'Referer': f'{WPS_BASE}/',
        'Origin': WPS_BASE,
        'Accept': 'application/json',
        'User-Agent': BROWSER_UA,
    }


def _raise_as_auth(exc: OpError) -> OpError:
    if exc.kind == 'parse':
        return OpError(f'Cookie 失效：响应非 JSON（疑似重定向登录页）｜{exc}', kind='auth')
    return exc


class WpsLingxiAdapter(Adapter):
    platform = 'wps'
    title = 'WPS 灵犀'
    credential_kind = 'cookie'

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        cookie = str(creds.get('cookie') or '').strip()
        if not cookie:
            raise OpError('缺少 Cookie', kind='auth')
        headers = _headers(cookie)
        try:
            resp = http_json('GET', f'{WPS_BASE}/api/public/v1/tasks', headers)
        except OpError as exc:
            raise _raise_as_auth(exc) from None

        tasks = (resp.get('data') or {}).get('tasks') or []
        task = next((t for t in tasks if isinstance(t, dict) and
                     (t.get('task_key') or t.get('key')) == 'daily_check_in'), None)
        if task is None:
            return CheckinResult('error', '任务列表里没有 daily_check_in（账号可能未开通灵犀每日签到）')
        status = str(task.get('status') or '').lower()
        if 'pending' in status:
            return CheckinResult('busy', f'服务器拥挤（任务 status={status}），稍后自动重试')
        if any(w in status for w in CLAIMED_WORDS):
            return CheckinResult('already', '今日已签到')

        try:
            resp = http_json('POST', f'{WPS_BASE}/api/public/v1/tasks/daily_check_in/claim',
                             headers, body={})
        except OpError as exc:
            raise _raise_as_auth(exc) from None
        data = resp.get('data') if isinstance(resp, dict) else None
        if not isinstance(data, dict):
            return CheckinResult('error', f'领取响应缺少 data：{str(resp)[:120]}')
        after = str(data.get('status') or '').lower()
        if 'pending' in after:
            return CheckinResult('busy', f'服务器拥挤，稍后自动重试：{after}')
        reward = data.get('reward_amount') or task.get('reward_amount') or 0
        return CheckinResult('ok', f'WPS 灵犀签到成功 +{reward} 积分', f'+{reward} 积分')


    def credits(self, creds: dict[str, Any]) -> str | None:
        resp = http_json('GET', f'{WPS_BASE}/api/public/v1/credits/balance',
                         _headers(str(creds.get('cookie') or '')))
        value = (resp.get('data') or {}).get('total_balance') if isinstance(resp, dict) else None
        return str(value) if value is not None else None


register(WpsLingxiAdapter())
