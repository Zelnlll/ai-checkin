"""魔搭 ModelScope（www.modelscope.cn）：无 claim 接口，服务端按"登录日首访"发放魔粒。

判定：Bearer ms- SDK 令牌 GET /openapi/v1/magicubes/earn/rules，
读 daily_active + aliyun_bindlogin 的 today_earned_amount 求和（实证源 ms_capture.json）。
未发放时 trigger_visit 用 Cookie 模拟首访后复查；仍为 0 返回 busy 不误报。
09-23 归因冒烟后可把 trigger_visit 升级为 Playwright 浏览器访问（②B 镜像内置）。
"""

from __future__ import annotations

import time
from typing import Any

from app.http import OpError, http_json
from app.platforms import register
from app.platforms.base import Adapter, CheckinResult

MS_BASE = 'https://www.modelscope.cn'
DAILY_RULE_KEYS = ('daily_active', 'aliyun_bindlogin')
RECHECK_SECONDS = 5

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36')

_sleep = time.sleep


def _rules(token: str) -> list[dict[str, Any]]:
    resp = http_json('GET', f'{MS_BASE}/openapi/v1/magicubes/earn/rules', {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': BROWSER_UA,
    })
    if not isinstance(resp, dict) or not resp.get('success'):
        msg = str((resp or {}).get('message') if isinstance(resp, dict) else resp)[:120]
        raise _BusinessError(f'rules 查询失败：{msg}')
    return [r for r in resp.get('data') or [] if isinstance(r, dict)]


def _today_earned(rules: list[dict[str, Any]]) -> int:
    return sum(int(r.get('today_earned_amount') or 0)
               for r in rules if r.get('rule_key') in DAILY_RULE_KEYS)


class _BusinessError(Exception):
    pass


def trigger_visit(cookie: str) -> None:
    """HTTP 首访触发（待 09-23 归因；失败静默，由复查结果定论）。"""
    headers = {'Cookie': cookie, 'Accept': 'application/json',
               'User-Agent': BROWSER_UA, 'Referer': f'{MS_BASE}/magicube/usage'}
    for path in ('/magicube/usage', '/api/v1/users/binding/check'):
        try:
            http_json('GET', f'{MS_BASE}{path}', headers)
        except Exception:
            pass


class ModelscopeAdapter(Adapter):
    platform = 'modelscope'
    title = '魔塔'
    credential_kind = 'token'

    def checkin(self, creds: dict[str, Any]) -> CheckinResult:
        token = str(creds.get('token') or '').strip()
        if not token:
            raise OpError('缺少 SDK 令牌（ms- 开头，个人中心可复制）', kind='auth')
        try:
            earned = _today_earned(_rules(token))
        except _BusinessError as exc:
            return CheckinResult('error', str(exc))
        if earned > 0:
            return CheckinResult('already', '今日魔粒已发放', f'+{earned} 魔粒')
        trigger_visit(str(creds.get('cookie') or ''))
        _sleep(RECHECK_SECONDS)
        try:
            earned = _today_earned(_rules(token))
        except _BusinessError as exc:
            return CheckinResult('error', str(exc))
        if earned > 0:
            return CheckinResult('ok', f'魔塔首访触发发放成功 +{earned} 魔粒',
                                 f'+{earned} 魔粒')
        return CheckinResult('busy', '今日未发放，将在重试窗口再查')

    def credits(self, creds: dict[str, Any]) -> str | None:
        resp = http_json('GET', f'{MS_BASE}/openapi/v1/magicubes/balance', {
            'Authorization': f"Bearer {str(creds.get('token') or '').strip()}",
            'Accept': 'application/json',
            'User-Agent': BROWSER_UA,
        })
        if isinstance(resp, dict) and resp.get('success'):
            value = (resp.get('data') or {}).get('available_balance')
            return str(value) if value is not None else None
        return None


register(ModelscopeAdapter())
