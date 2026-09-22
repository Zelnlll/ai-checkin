"""Link AI（link-ai.tech）：Bearer JWT 鉴权，签到以成长任务 SIGN 的 done 为准。

协议源：agent_ext.rs L1442-1580 + 用户 2026-09-22 实测（870=重复签到，benefits 已到账）。
判"已签"只认一个证据：任务状态里 SIGN 已 done；870 且任务仍未完成=真拒签，如实报错。
"""

from __future__ import annotations

import time
from typing import Any

from app.http import OpError, http_json, jwt_exp_s
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

LINKAI_BASE = 'https://link-ai.tech'

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36')

TASKS_PATH = '/api/chat/web/app/user/growth/task/list'
SIGNIN_PATH = '/api/chat/web/app/user/sign/in'
BALANCE_PATH = '/api/chat/web/app/user/get/balance'


def _headers(token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'User-Agent': BROWSER_UA,
        'Referer': f'{LINKAI_BASE}/console/account',
    }


def _raise_as_auth(exc: OpError) -> OpError:
    if exc.kind == 'parse':
        return OpError(f'token 失效：响应非 JSON（请重新复制 localStorage.token）｜{exc}',
                       kind='auth')
    return exc


def _data(resp: Any) -> Any:
    if not isinstance(resp, dict) or not resp.get('success'):
        code = (resp or {}).get('code') if isinstance(resp, dict) else None
        msg = str((resp or {}).get('message') or '请求失败') if isinstance(resp, dict) else str(resp)[:80]
        raise _BusinessError(f'code={code} {msg}')
    return resp.get('data')


class _BusinessError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _sign_done(data: Any) -> bool | None:
    def in_tasks(tasks):
        for task in tasks or []:
            if isinstance(task, dict) and task.get('code') == 'SIGN':
                return bool(task.get('done'))
        return None
    if not isinstance(data, dict):
        return None
    for cat in data.get('categories') or []:
        found = in_tasks(cat.get('tasks') if isinstance(cat, dict) else None)
        if found is not None:
            return found
    for key in ('tasks', 'list', 'records', 'items'):
        found = in_tasks(data.get(key))
        if found is not None:
            return found
    return None


class LinkaiAdapter(Adapter):
    platform = 'linkai'
    title = 'Link AI'
    credential_kind = 'token'

    def _tasks_done(self, headers: dict) -> bool | None:
        try:
            return _sign_done(_data(http_json('GET', f'{LINKAI_BASE}{TASKS_PATH}', headers)))
        except _BusinessError:
            return None

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        token = str(creds.get('token') or '').strip()
        if not token:
            raise OpError('缺少 token（客户端 leveldb 或 F12 localStorage.token）', kind='auth')
        headers = _headers(token)
        try:
            if self._tasks_done(headers) is True:
                return CheckinResult('already', '今日已签到')
            try:
                data = _data(http_json('GET', f'{LINKAI_BASE}{SIGNIN_PATH}', headers))
            except _BusinessError as exc:
                if self._tasks_done(headers) is True:   # 拒签也可能是重复签，以任务为准
                    return CheckinResult('already', '今日已签到')
                return CheckinResult(
                    'error',
                    f'{exc.message}——每日签到仍未完成；若网页端要求拼图验证则无法自动签到，'
                    '请去 link-ai.tech 控制台手动签一次确认')
            score = None
            if isinstance(data, dict):
                for key in ('score', 'points', 'credit'):
                    if isinstance(data.get(key), (int, float)):
                        score = int(data[key])
                        break
            if score is not None:
                return CheckinResult('ok', f'Link AI 签到成功 +{score}', f'+{score}')
            return CheckinResult('ok', '签到成功（随机积分，数额以积分为准）', '+?')
        except OpError as exc:
            raise _raise_as_auth(exc) from None

    def credits(self, creds: dict[str, Any]) -> str | None:
        data = _data(http_json('GET', f'{LINKAI_BASE}{BALANCE_PATH}',
                               _headers(str(creds.get('token') or ''))))
        score = data.get('score') if isinstance(data, dict) else None
        return str(score) if score is not None else None

    def token_status(self, creds: dict[str, Any]) -> dict[str, Any]:
        import datetime as dt
        exp = jwt_exp_s(str(creds.get('token') or ''))
        if not exp:
            return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
        left = exp - time.time()
        return {'known': True, 'expired': left <= 0,
                'expires_at': dt.datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M'),
                'days_left': round(left / 86400, 1)}


register(LinkaiAdapter())
