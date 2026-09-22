"""网页「签到中心」面板：进度条 + 每平台彩色卡片（标准库 http.server，零依赖）。

数据只读：state.json + 凭证仓库；serve() 每次请求实时聚合。
"""

from __future__ import annotations

import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.credentials import CredentialStore
from app.platforms import ADAPTERS, get_adapter
from app.state import DailyState

_ACCENTS = {
    'wps': '#22b14c', 'dazi': '#3b82f6', 'minimax': '#8b5cf6',
    'qoder': '#ca8a04', 'modelscope': '#f59e0b',
}
_PILL = {
    'ok': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'already': ('已签到 ✔', '#eef2ff', '#4f46e5'),
    'busy': ('待重试 ⏳', '#fef9c3', '#a16207'),
    'error': ('失败 ❌', '#fee2e2', '#dc2626'),
    '': ('今日未执行', '#f3f4f6', '#6b7280'),
}


def collect_status(cfg, store: CredentialStore, state: DailyState,
                   platforms: list[str]) -> dict[str, Any]:
    today = dt.date.today().isoformat()
    items = []
    done = 0
    for platform in platforms:
        adapter = get_adapter(platform)
        rec = state.get(platform, today) or {}
        if rec.get('state') in ('ok', 'already'):
            done += 1
        creds = store.load(platform)
        credential = '已导入' if creds else '未导入凭证'
        if creds:
            report = store.expiry_report(platform, creds, adapter)
            if report.get('expired') or report.get('likely_expired_soon'):
                credential = '凭证临期/失效 ⚠'
        items.append({
            'platform': platform, 'title': adapter.title,
            'state': rec.get('state', ''), 'message': rec.get('message', ''),
            'reward': rec.get('reward', ''), 'balance': rec.get('balance', ''),
            'streak': rec.get('streak', 0), 'at': rec.get('at', ''),
            'credential': credential,
        })
    return {'today': today, 'done': done, 'total': len(items), 'platforms': items}


def _card(p: dict[str, Any]) -> str:
    accent = _ACCENTS.get(p['platform'], '#6b7280')
    text, bg, fg = _PILL.get(p['state'], _PILL[''])
    if p['credential'] != '已导入':
        text, bg, fg = p['credential'], '#f3f4f6', '#6b7280'
    big = p['reward'] or text
    extras = []
    if p['balance']:
        extras.append(f"余{p['balance']}")
    if p['streak'] >= 2:
        extras.append(f"连{p['streak']}天")
    sub = '｜'.join(extras) or (p['message'][:30] if p['state'] == 'error' else '')
    at = f"上次执行 {p['at']}" if p['at'] else ''
    return (
        f'<div class="card" style="border-top-color:{accent}">'
        f'<div class="row"><span class="name">{p["title"]}</span>'
        f'<span class="pill" style="background:{bg};color:{fg}">{text}</span></div>'
        f'<div class="big" style="color:{accent}">{big}</div>'
        f'<div class="sub">{sub}<span class="at">{at}</span></div></div>'
    )


def render_html(status: dict[str, Any]) -> str:
    pct = int(status['done'] / status['total'] * 100) if status['total'] else 0
    cards = '\n'.join(_card(p) for p in status['platforms'])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>签到中心</title><style>
body {{ margin:0; padding:20px; background:#f3f6f9;
       font-family:'Microsoft YaHei','PingFang SC',sans-serif; }}
.wrap {{ max-width:960px; margin:0 auto; }}
.head {{ background:#fff; border-radius:14px; padding:18px 24px; margin-bottom:18px;
        box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.title {{ font-size:22px; font-weight:700; }}
.bar {{ height:10px; background:#e5e7eb; border-radius:5px; margin-top:14px; overflow:hidden; }}
.fill {{ height:100%; background:linear-gradient(90deg,#34d399,#10b981); width:{pct}%; }}
.meta {{ display:flex; justify-content:space-between; font-size:14px; margin-top:8px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px; }}
.card {{ background:#fff; border-radius:12px; border-top:4px solid #666;
        padding:16px 18px; box-shadow:0 1px 4px rgba(0,0,0,.05); }}
.row {{ display:flex; justify-content:space-between; align-items:center; }}
.name {{ font-size:16px; font-weight:600; }}
.pill {{ font-size:12px; border-radius:10px; padding:2px 8px; }}
.big {{ font-size:28px; font-weight:800; margin:12px 0 6px; }}
.sub {{ font-size:12px; color:#6b7280; display:flex; justify-content:space-between; }}
</style></head><body><div class="wrap">
<div class="head"><div class="title">📋 签到中心</div>
<div class="bar"><div class="fill"></div></div>
<div class="meta"><span>今日签到进度 {status['today']}</span>
<span>已签 {status['done']} / {status['total']}</span></div></div>
<div class="grid">
{cards}
</div></div></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        cfg = self.server.cfg
        store = CredentialStore(cfg.data_dir, set(ADAPTERS))
        state = DailyState(cfg.data_dir)
        status = collect_status(cfg, store, state, list(ADAPTERS))
        if self.path.startswith('/api/status'):
            body, ctype = json.dumps(status, ensure_ascii=False).encode('utf-8'), \
                'application/json; charset=utf-8'
        else:
            body, ctype = render_html(status).encode('utf-8'), \
                'text/html; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(cfg, port: int = 8000) -> None:
    httpd = ThreadingHTTPServer(('0.0.0.0', port), _Handler)
    httpd.cfg = cfg
    print(f'签到中心已启动：http://0.0.0.0:{port}')
    httpd.serve_forever()
