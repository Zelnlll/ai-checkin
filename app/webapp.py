"""网页「签到中心」：严格对齐设计稿（图标/胶囊/大数字/明细行/一键签到）+ 设置页。

路由：GET / 仪表盘 | GET /settings 设置 | GET /api/status
     POST /api/checkin/<p> 一键签到 | POST /api/credentials/<p> 导入凭证 |
     POST /api/login/<p> 网页登录（Playwright，容器内有头能力时扫码）
仅内网使用，无鉴权。
"""

from __future__ import annotations

import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.credentials import CredentialStore
from app.platforms import ADAPTERS, get_adapter
from app.scanner import scan_local_accounts
from app.state import DailyState

_ACCENTS = {
    'wps': '#22b14c', 'dazi': '#3b82f6', 'minimax': '#8b5cf6',
    'qoder': '#ca8a04', 'modelscope': '#f59e0b',
}
_PILL = {
    'ok': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'already': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'busy': ('待重试 ⏳', '#fef9c3', '#a16207'),
    'error': ('失败 ❌', '#fee2e2', '#dc2626'),
    '': ('今日未执行', '#f3f4f6', '#6b7280'),
}
_BROWSER_LOGIN = {'wps', 'dazi', 'minimax', 'modelscope'}
# 平台 → 需要的凭证字段与提示（魔搭双入口：只填令牌也能与已存 Cookie 增量合并）
_CRED_FIELDS = {
    'wps': [('cookie', 'Cookie 整串（含 wps_sid）')],
    'dazi': [('cookie', 'Cookie 整串（含 bce-user-info）')],
    'minimax': [('token', 'token（JWT，抓包或 localStorage）')],
    'qoder': [('token', 'Bearer 后的 dt- 设备令牌（抓包 openapi.qoder.com.cn）')],
    'modelscope': [('cookie', '会话 Cookie 整串（含 m_session_id）'),
                   ('token', 'SDK 令牌（ms- 开头，个人中心）')],
}


def _last_done(state: DailyState, platform: str, today: str) -> str:
    data = state._load()
    for day in sorted((d for d in data if d < today), reverse=True):
        rec = data[day].get(platform)
        if rec and rec.get('state') in ('ok', 'already'):
            return day
    return ''


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
            'keepalive': rec.get('keepalive', ''),
            'last_done': _last_done(state, platform, today),
            'credential': credential,
        })
    return {'today': today, 'done': done, 'total': len(items), 'platforms': items}


def _rows(p: dict[str, Any]) -> str:
    rows = [('今日已得', p['reward'] or '—'),
            ('余额', p['balance'] or '—'),
            ('连续签到', f"{p['streak']} 天" if p['streak'] else '—'),
            ('上次签到', p['last_done'] or '—'),
            ('上次执行', p['at'] or '—'),
            ('保活', p['keepalive'] or '—')]
    return '\n'.join(
        f'<div class="kv"><span>{k}</span><span>{v}</span></div>' for k, v in rows)


def _card(p: dict[str, Any]) -> str:
    accent = _ACCENTS.get(p['platform'], '#6b7280')
    text, bg, fg = _PILL.get(p['state'], _PILL[''])
    big = p['reward'] or {'busy': '待重试', 'error': '失败',
                          '': '未执行'}.get(p['state'], '已签到')
    if p['credential'] != '已导入':
        text, bg, fg = p['credential'], '#f3f4f6', '#6b7280'
        big = '未导入凭证'
    initial = p['title'][:1]
    if p['credential'] != '已导入':
        btn = ('<a class="btn gray" href="/settings">导入凭证</a>')
    elif p['state'] in ('ok', 'already'):
        btn = '<button class="btn gray" disabled>今日已签到</button>'
    else:
        btn = (f'<button class="btn blue" onclick="doCheckin(\'{p["platform"]}\')">'
               '立即签到</button>')
    return (
        f'<div class="card">'
        f'<div class="row"><span class="icon" style="background:{accent}1a;color:{accent}">'
        f'{initial}</span><span class="name">{p["title"]}</span>'
        f'<span class="pill" style="background:{bg};color:{fg}">{text}</span></div>'
        f'<div class="big" style="color:{accent}">{big}</div>'
        f'<div class="kvwrap">{_rows(p)}</div>{btn}</div>'
    )


_STYLE = """
body { margin:0; padding:20px; background:#f3f6f9;
       font-family:'Microsoft YaHei','PingFang SC',sans-serif; }
.wrap { max-width:1000px; margin:0 auto; }
.head { background:#fff; border-radius:14px; padding:18px 24px; margin-bottom:18px;
        box-shadow:0 1px 4px rgba(0,0,0,.06); }
.title { font-size:22px; font-weight:700; }
.slogan { font-size:13px; color:#6b7280; margin-top:2px; }
.bar { height:10px; background:#e5e7eb; border-radius:5px; margin-top:14px; overflow:hidden; }
.fill { height:100%; background:linear-gradient(90deg,#34d399,#10b981); }
.meta { display:flex; justify-content:space-between; font-size:14px; margin-top:8px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }
.card { background:#fff; border-radius:12px; padding:18px; box-shadow:0 1px 4px rgba(0,0,0,.05);
        display:flex; flex-direction:column; }
.row { display:flex; align-items:center; gap:10px; }
.icon { width:34px; height:34px; border-radius:10px; display:flex; align-items:center;
        justify-content:center; font-weight:700; font-size:16px; }
.name { font-size:16px; font-weight:600; flex:1; }
.pill { font-size:12px; border-radius:10px; padding:2px 8px; white-space:nowrap; }
.big { font-size:30px; font-weight:800; margin:14px 0 10px; }
.kvwrap { border-top:1px solid #f1f2f4; }
.kv { display:flex; justify-content:space-between; font-size:13px; color:#374151;
      padding:7px 2px; border-bottom:1px solid #f1f2f4; }
.kv span:last-child { color:#111827; font-weight:500; }
.btn { margin-top:14px; border:0; border-radius:8px; padding:10px 0; width:100%;
       font-size:14px; cursor:pointer; text-align:center; text-decoration:none;
       display:block; box-sizing:border-box; }
.btn.blue { background:#2563eb; color:#fff; }
.btn.gray { background:#eef0f3; color:#9ca3af; cursor:default; }
.foot { text-align:center; color:#9ca3af; font-size:12px; margin-top:22px; }
"""

_JS = """
async function doCheckin(p){
  const r = await fetch('/api/checkin/'+p,{method:'POST'});
  const j = await r.json();
  alert(j.ok ? ('签到结果：'+j.state+' '+j.message) : ('失败：'+j.message));
  location.reload();
}
async function saveCred(p){
  const body = {};
  document.querySelectorAll('[data-p="'+p+'"]').forEach(el => {
    if (el.value.trim()) body[el.dataset.field] = el.value.trim();
  });
  if (!body.cookie && !body.token) { alert('请先粘贴内容'); return; }
  const r = await fetch('/api/credentials/'+p,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j = await r.json();
  alert(j.ok ? '凭证已保存并导入' : ('失败：'+j.message));
}
async function scanLocal(){
  const r = await fetch('/api/scan',{method:'POST'});
  const j = await r.json();
  alert(j.ok && j.platforms.length ? ('已导入：'+j.platforms.join('、')) : (j.message || '未发现可导入账号'));
  location.reload();
}
async function clearCred(p){
  if (!confirm('清空该平台凭证？')) return;
  const r = await fetch('/api/credentials/'+p,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({clear:true})});
  const j = await r.json();
  alert(j.ok ? '已清空' : ('失败：'+j.message));
  location.reload();
}
async function webLogin(p){
  alert('已发起网页登录，请稍候（最长5分钟）…');
  const r = await fetch('/api/login/'+p,{method:'POST'});
  const j = await r.json();
  alert(j.ok ? '登录成功，Cookie 已导入' : ('未完成：'+j.message));
}
"""


def render_html(status: dict[str, Any]) -> str:
    pct = int(status['done'] / status['total'] * 100) if status['total'] else 0
    cards = '\n'.join(_card(p) for p in status['platforms'])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>签到中心</title><style>{_STYLE}</style><script>{_JS}</script></head>
<body><div class="wrap">
<div class="head"><div class="title">📋 签到中心</div>
<div class="slogan">多个签到一目了然 · 一键完成 · <a href="/settings">设置</a></div>
<div class="bar"><div class="fill" style="width:{pct}%"></div></div>
<div class="meta"><span>今日签到进度 {status['today']}</span>
<span>已签 {status['done']} / {status['total']}</span></div></div>
<div class="grid">
{cards}
</div>
<div class="foot">所有签到均在服务端执行，数据来自各平台官方接口<br>
新增签到只需在服务端加一个适配器，本页自动多出一张卡</div>
</div></body></html>"""


def render_settings(status: dict[str, Any]) -> str:
    blocks = []
    for p in status['platforms']:
        fields = _CRED_FIELDS.get(p['platform'], [('cookie', 'Cookie 整串')])
        inputs = '\n'.join(
            f'<div class="slogan" style="margin:8px 0 4px">{label}</div>'
            f'<textarea id="cred-{p["platform"]}-{name}" data-p="{p["platform"]}" '
            f'data-field="{name}" rows="3" style="width:100%;'
            f'box-sizing:border-box;border:1px solid #d1d5db;border-radius:8px;'
            f'padding:8px;font-size:12px"></textarea>'
            for name, label in fields)
        login_btn = (
            f'<button class="btn blue" style="margin-top:8px;width:auto;padding:8px 16px"'
            f''' onclick="webLogin('{p['platform']}')"''' '>网页登录获取</button>'
            if p['platform'] in _BROWSER_LOGIN else '')
        blocks.append(
            f'<div class="card"><div class="row"><span class="name">{p["title"]}</span>'
            f'<span class="pill" style="background:#f3f4f6;color:#6b7280">'
            f'{p["credential"]}</span></div>'
            + inputs +
            f'<button class="btn blue" style="margin-top:8px;width:auto;padding:8px 16px" '
            f'''onclick="saveCred('{p['platform']}')"''' '>保存并导入</button>'
            + login_btn +
            f'<button class="btn gray" style="margin-top:8px;width:auto;padding:8px 16px" '
            f'''onclick="clearCred('{p['platform']}')"''' '>清空凭证</button></div>')
    cards = '\n'.join(blocks)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>设置 · 签到中心</title><style>{_STYLE}</style><script>{_JS}</script></head>
<body><div class="wrap">
<div class="head"><div class="title">⚙️ 设置</div>
<div class="slogan">导入各平台凭证 · <a href="/">返回签到中心</a></div>
<button class="btn blue" style="margin-top:10px;width:auto;padding:8px 16px"
 onclick="scanLocal()">🔍 扫描本机账号导入</button></div>
<div class="grid">
{cards}
</div></div></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str) -> None:
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        cfg = self.server.cfg
        store = CredentialStore(cfg.data_dir, set(ADAPTERS))
        state = DailyState(cfg.data_dir)
        return cfg, store, state, collect_status(cfg, store, state, list(ADAPTERS))

    def do_GET(self):
        try:
            self._get()
        except Exception as exc:
            self._json({'ok': False, 'message': f'{type(exc).__name__}: {exc}'}, 500)

    def _get(self):
        *_, status = self._status()
        if self.path.startswith('/api/status'):
            self._json(status)
        elif self.path.startswith('/settings'):
            self._html(render_settings(status))
        else:
            self._html(render_html(status))

    def do_POST(self):
        try:
            self._post()
        except Exception as exc:
            self._json({'ok': False, 'message': f'{type(exc).__name__}: {exc}'}, 500)

    def _post(self):
        cfg, store, state, _ = self._status()
        length = min(int(self.headers.get('Content-Length') or 0), 1024 * 1024)
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            payload = {}
        kind, _, platform = self.path.rpartition('/')
        head = kind.rstrip('/')
        if self.path.startswith('/api/scan'):
            found = scan_local_accounts(cfg.data_dir / 'inbox')
            store.import_inbox()
            self._json({'ok': True, 'platforms': found, 'message': '、'.join(found) or '未发现可导入账号'})
            return
        if platform not in ADAPTERS:
            self._json({'ok': False, 'message': f'未知平台 {platform}'}, 404)
            return
        if head.endswith('/api/credentials'):
            if payload.get('clear'):
                self._json({'ok': True, **store.clear(platform)})
                return
            if not (payload.get('cookie') or payload.get('token')):
                self._json({'ok': False, 'message': '需提供 cookie 或 token 字段'})
                return
            inbox = cfg.data_dir / 'inbox'
            inbox.mkdir(parents=True, exist_ok=True)
            (inbox / f'{platform}.json').write_text(
                json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            store.import_inbox()
            self._json({'ok': True, 'message': '已导入'})
        elif head.endswith('/api/checkin'):
            from app.main import cmd_run_once
            outcomes = cmd_run_once(cfg, platforms=[platform], store=store,
                                    state=state, notifier=_NoopNotifier())
            r = outcomes[0].result
            self._json({'ok': r.state in ('ok', 'already'),
                        'state': r.state, 'message': r.message})
        elif head.endswith('/api/login'):
            from app.browser_login import browser_login
            code = browser_login(cfg, platform, headful=False)
            self._json({'ok': code == 0,
                        'message': '成功' if code == 0 else f'退出码 {code}（可能需有头扫码）'})
        else:
            self._json({'ok': False, 'message': '未知接口'}, 404)

    def log_message(self, *args):
        pass


class _NoopNotifier:
    def push(self, outcomes, today):
        return True


def serve_app(cfg, port: int = 8000) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(('0.0.0.0', port), _Handler)
    httpd.cfg = cfg
    return httpd


def serve(cfg, port: int = 8000) -> None:
    httpd = serve_app(cfg, port)
    print(f'签到中心已启动：http://0.0.0.0:{port}')
    httpd.serve_forever()
