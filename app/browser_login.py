"""容器/PC 端浏览器登录（Playwright）：storage_state 持久化 + Cookie 自动抓取。

容器内后台运行（②B）：`python -m app.main login <platform>`；
storage_state 存 DATA_DIR/browser/<platform>.json，有效时静默刷新 Cookie 写 inbox；
失效时：无头→截图 login_stuck 并告警退出码 3；有头（--headful，PC 端）→等待人工登录。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# 登录页 / 判定登录成功的关键 Cookie / 归属域（minimax 的 token 存 localStorage）
PLATFORM_LOGIN: dict[str, dict[str, Any]] = {
    'wps': {'url': 'https://lingxi.kdocs.cn/', 'cookie': 'wps_sid'},
    'dazi': {'url': 'https://console.bce.baidu.com/', 'cookie': 'bce-user-info'},
    'modelscope': {'url': 'https://www.modelscope.cn/', 'cookie': 'm_session_id'},
    'minimax': {'url': 'https://agent.minimaxi.com/', 'local_storage': 'token',
                'web_session': True,
                'capture': {'url': 'minimax-cloud', 'header': 'token'}},
    'linkai': {'url': 'https://link-ai.tech/console/account',
               'local_storage': 'token',
               'capture': {'url': 'link-ai.tech/api', 'header': 'authorization',
                           'strip': 'Bearer '}},
}


def _capture_request(spec: dict[str, Any], captured: dict[str, str],
                     request) -> None:
    """按 spec['capture'] 从真实外发请求抓 API 认的票据（首见优先）。"""
    cap = spec.get('capture')
    if not cap or cap['url'] not in request.url:
        return
    if not captured.get('token'):
        v = request.headers.get(cap['header'], '')
        strip = cap.get('strip', '')
        if strip and v.startswith(strip):
            v = v[len(strip):]
        if v:
            captured['token'] = v
    if 'user_id' not in captured:
        from urllib.parse import parse_qs, urlparse
        uid = parse_qs(urlparse(request.url).query).get('user_id')
        if uid and uid[0] not in ('', 'undefined'):
            captured['user_id'] = uid[0]


def _extract_state(context, header_token: str = '') -> dict[str, str] | None:
    """token 一律取网站实际外发的请求头 token（与 F12 手动复制同源，杜绝抓错会话 JWT）。"""
    creds: dict[str, str] = {}
    cookies = context.cookies()
    if cookies:
        creds['cookie'] = '; '.join(f"{c['name']}={c['value']}" for c in cookies)
    if header_token:
        creds['token'] = header_token
    return creds or None


def _login_done(spec: dict[str, Any], creds: dict[str, str] | None) -> bool:
    if not creds:
        return False
    marker = spec.get('cookie')
    if marker and marker in creds.get('cookie', ''):
        return True
    return bool(spec.get('local_storage')) and spec['local_storage'] in creds


def browser_login(cfg, platform: str, headful: bool = False) -> int:
    spec = PLATFORM_LOGIN.get(platform)
    if spec is None:
        print(f'平台 {platform} 不支持浏览器登录，可选：{", ".join(PLATFORM_LOGIN)}')
        print('qoder 请按 README 手动粘贴 token 到 inbox。')
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('缺少 playwright：pip install playwright && playwright install chromium')
        return 2

    browser_dir = Path(cfg.data_dir) / 'browser'
    browser_dir.mkdir(parents=True, exist_ok=True)
    state_file = browser_dir / f'{platform}.json'
    timeout_s = int(__import__('os').environ.get('LOGIN_TIMEOUT', '300'))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful, args=['--no-sandbox'])
        ctx_kwargs = {'storage_state': str(state_file)} if state_file.exists() else {}
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        # 从网站真实外发请求抓 API 认的票据（与 F12 手动复制同源）
        captured: dict[str, str] = {}
        sample_headers: dict[str, str] = {}

        def _on_request(request):
            before = captured.get('token')
            _capture_request(spec, captured, request)
            if captured.get('token') and captured['token'] != before:
                sample_headers.update(request.headers)
        context.on('request', _on_request)
        page.goto(spec['url'], wait_until='domcontentloaded')
        deadline = time.time() + timeout_s
        found: dict[str, str] | None = None
        while time.time() < deadline:
            creds = _extract_state(context, captured.get('token', ''))
            if _login_done(spec, creds):
                found = creds
                break
            if headful:
                time.sleep(2)
                continue
            # 无头且无有效 state：不可能完成交互登录，截图退出
            shot = browser_dir / f'login_stuck_{platform}.png'
            page.screenshot(path=str(shot))
            browser.close()
            print(f'无头登录失败（需要人工交互），截图：{shot}')
            print('请在 PC 端运行：python -m app.main login '
                  f'{platform} --headful，然后把 inbox 文件拷入容器。')
            return 3
        if not found:
            browser.close()
            print(f'登录超时（{timeout_s}s），未检测到关键 Cookie')
            return 3
        context.storage_state(path=str(state_file))
        browser.close()

    inbox = Path(cfg.data_dir) / 'inbox'
    inbox.mkdir(parents=True, exist_ok=True)
    out = inbox / f'{platform}.json'
    if spec.get('web_session'):
        found['web_session'] = True
        found.update(captured)
    if sample_headers:
        found['_sample_headers'] = dict(sample_headers)
    out.write_text(json.dumps(found, ensure_ascii=False), encoding='utf-8')
    print(f'已抓取 {platform} 凭证 → {out}')
    return 0
