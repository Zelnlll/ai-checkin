"""MiniMax「web 会话 token」传输：签名协议同 desktop，但 query 必须复刻
web 前端全套设备参数集（实测缺 timezone_id 等参数时网关直接 401 空响应；
参数齐了纯 HTTP 即可，无需浏览器）。参数模板逆向自 GitHub Minatoxiaohu/
agent-auto-signin（2026-09-09 全链路实测口径），本机 2026-09-23 复验 200。

desktop token（F12/客户端）继续走 app.platforms.minimax 的极简 query；
`login minimax` 抓到的 web 会话凭证带 web_session 标记 → 自动切本模块。
"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import quote, urlencode

from app.http import OpError, http_json
from app.platforms.minimax import MINIMAX_BASE, _JS_UNRESERVED, minimax_headers

BASE = MINIMAX_BASE


def _jwt_user_id(token: str) -> str:
    try:
        p = token.split('.')[1]
        p += '=' * (-len(p) % 4)
        return str(json.loads(base64.urlsafe_b64decode(p))['user']['id'])
    except Exception:
        return '0'


def build_web_path(path: str, token: str, now_ms: int | None = None) -> str:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    # 参数集合与顺序需与 web 前端一致；unix 出现两次、token 挂在 query 上
    params = [
        ('device_platform', 'web'), ('biz_id', '3'), ('app_id', '3001'),
        ('version_code', '22201'), ('unix', str(now_ms)),
        ('timezone_offset', '28800'), ('timezone_id', 'Asia/Shanghai'),
        ('sys_language', 'zh'), ('lang', 'zh'), ('uuid', 'null'),
        ('device_id', '51489187'), ('os_name', 'Windows'),
        ('browser_name', 'Chrome'), ('browser_language', 'zh-CN'),
        ('browser_platform', 'Win32'), ('user_id', _jwt_user_id(token)),
        ('op_ticket', 'undefined'), ('screen_width', '1280'),
        ('screen_height', '720'), ('unix', str(now_ms)), ('token', token),
    ]
    return path.split('?')[0] + '?' + \
        urlencode(params, quote_via=quote, safe=_JS_UNRESERVED)


def web_request(path: str, body: dict | None, token: str,
                now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    path_q = build_web_path(path, token, now_ms)
    body_str = json.dumps(body, ensure_ascii=False) if body is not None else ''
    h = minimax_headers(token, path_q, body_str,
                        ts=str(now_ms // 1000), ms=str(now_ms))
    h.update({'Origin': BASE, 'Referer': BASE + '/',
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/126.0.0.0 Safari/537.36'})
    try:
        if body is not None:
            return http_json('POST', BASE + path_q, h, body)
        return http_json('GET', BASE + path_q, h)
    except OpError as exc:
        if '401' in str(exc) or '403' in str(exc):
            raise OpError('web 会话失效/签名拒绝：PC 重跑 login minimax 再导入',
                          kind='auth') from None
        raise
