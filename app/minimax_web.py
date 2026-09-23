"""MiniMax「web 会话」传输：网关对脚本客户端有指纹级防护，HTTP 裸请求恒 401，
必须在登录态 Chromium 页内 fetch（Playwright，NAS 镜像已内置）。

desktop token（F12/客户端）仍走 app.platforms.minimax 的纯 HTTP；
`login minimax` 抓到的 web 会话凭证带 browser_state 字段 → 自动切本模块。
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from app.http import OpError
from app.platforms.minimax import MINIMAX_BASE, _JS_UNRESERVED, minimax_headers

ORIGIN = MINIMAX_BASE

# 与真实网页请求逐参数一致（unix/token/user_id 动态；签名基于整条 query）
_STATIC_PARAMS = [
    ('device_platform', 'web'), ('biz_id', '3'), ('app_id', '3001'),
    ('version_code', '22201'),
    ('timezone_offset', '28800'), ('sys_language', 'zh'), ('lang', 'zh'),
    ('uuid', 'dd5f3cc8-ba12-47ae-b63f-17c85721b223'),
    ('device_id', '51489187'), ('os_name', 'Windows'),
    ('browser_name', 'Chrome'), ('device_memory', '16'), ('cpu_core_num', '8'),
    ('browser_language', 'zh-CN'), ('browser_platform', 'Win32'),
    ('screen_width', '1280'), ('screen_height', '720'),
]


def _jwt_user_id(token: str) -> str:
    try:
        p = token.split('.')[1]
        p += '=' * (-len(p) % 4)
        return str(json.loads(base64.urlsafe_b64decode(p))['user']['id'])
    except Exception:
        return ''


def build_web_path(path: str, token: str, now_ms: int | None = None) -> str:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    params = [(k, v) for k, v in _STATIC_PARAMS]
    params.insert(4, ('unix', str(now_ms)))
    params += [('user_id', _jwt_user_id(token)), ('token', token),
               ('client', 'web')]
    return path.split('?')[0] + '?' + \
        urlencode(params, quote_via=quote, safe=_JS_UNRESERVED)


def in_page_fetch(state_rel: str, origin: str, path_q: str,
                  headers: dict[str, str], body: str | None = None) -> tuple:
    from playwright.sync_api import sync_playwright
    state = Path(os.environ.get('DATA_DIR', 'data')) / state_rel
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            ctx = b.new_context(storage_state=str(state))
            page = ctx.new_page()
            page.goto(origin + '/', wait_until='domcontentloaded')
            return tuple(page.evaluate(
                """async ([url, hdrs, body]) => {
                    const opt = {headers: hdrs};
                    if (body !== null) { opt.method = 'POST'; opt.body = body; }
                    const r = await fetch(url, opt);
                    return [r.status, await r.text()];
                }""", [origin + path_q, headers, body]))
        finally:
            b.close()


def web_request(path: str, body: dict | None, token: str,
                state_rel: str, now_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    path_q = build_web_path(path, token, now_ms)
    body_str = json.dumps(body, ensure_ascii=False) if body is not None else ''
    h = minimax_headers(token, path_q, body_str,
                        ts=str(now_ms // 1000), ms=str(now_ms))
    hdrs = {k: h[k] for k in ('token', 'x-timestamp', 'x-signature', 'yy')}
    hdrs['content-type'] = 'application/json'
    status, text = in_page_fetch(state_rel, ORIGIN, path_q, hdrs,
                                 body_str or None)
    if status == 401:
        raise OpError('HTTP 401（web 会话失效：PC 重跑 login minimax 再导入）',
                      kind='auth')
    if status >= 400:
        raise OpError(f'HTTP {status}：{text[:120]}', kind='http')
    try:
        return json.loads(text)
    except ValueError as exc:
        raise OpError(f'响应解析失败：{exc}', kind='parse') from exc
