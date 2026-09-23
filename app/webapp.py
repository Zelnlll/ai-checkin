"""网页「签到中心」：严格对齐设计稿（图标/胶囊/大数字/明细行/一键签到）+ 设置页。

路由：GET / 仪表盘 | GET /settings 设置 | GET /api/status
     POST /api/checkin/<p> 一键签到 | POST /api/credentials/<p> 导入凭证 |
     POST /api/login/<p> 网页登录（Playwright，容器内有头能力时扫码）
仅内网使用，无鉴权。
"""

from __future__ import annotations

import datetime as dt
import html as html_mod
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app import __version__
from app.credentials import CredentialStore, sanitize_acct_id, sanitize_label
from app.platforms import ADAPTERS, get_adapter
from app.scheduler import earliest_of, fmt_num, parse_num
from app.state import DailyState

_ACCENTS = {
    'wps': '#22b14c', 'dazi': '#3b82f6', 'minimax': '#8b5cf6',
    'qoder': '#ca8a04', 'modelscope': '#f59e0b', 'linkai': '#06b6d4',
    'workbuddy': '#38bdf8', 'trae': '#2dd4bf',
}
_PILL = {
    'ok': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'already': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'busy': ('待重试 ⏳', '#fef9c3', '#a16207'),
    'error': ('失败 ❌', '#fee2e2', '#dc2626'),
    '': ('今日未执行', '#f3f4f6', '#6b7280'),
}
# 平台 → 需要的凭证字段与提示（魔搭双入口：只填令牌也能与已存 Cookie 增量合并）
_CRED_FIELDS = {
    'wps': [('cookie', 'Cookie 整串（含 wps_sid）')],
    'dazi': [('cookie', 'Cookie 整串（含 bce-user-info）')],
    'minimax': [('token', 'token（JWT，抓包或 localStorage）')],
    'qoder': [('token', 'Bearer 后的 dt- 设备令牌（抓包 openapi.qoder.com.cn）')],
    'modelscope': [('cookie', '会话 Cookie 整串（含 m_session_id）'),
                   ('token', 'SDK 令牌（ms- 开头，个人中心）')],
    'linkai': [('token', 'JWT（扫描客户端自动获取，或 F12 console.log(localStorage.token)）')],
    'trae': [('token', 'Cloud-IDE-JWT（扫描 Trae 桌面端自动获取，或按 agent-auto-signin 从 storage.json 解密）')],
    'workbuddy': [('token', 'accessToken（扫描桌面端自动获取）'),
                  ('uid', 'X-User-Id'), ('enterprise_id', '企业 ID（可选）')],
}


def _last_done(state: DailyState, platform: str, today: str) -> str:
    """最近一次成功签到：日期 + 当时执行时刻合并成一条（今天则显示「今天」）。"""
    data = state._load()
    for day in sorted((d for d in data if d <= today), reverse=True):
        rec = data[day].get(platform)
        if rec and rec.get('state') in ('ok', 'already'):
            at = rec.get('at', '')
            label = '今天' if day == today else day
            return f'{label} {at}'.strip()
    return ''


def _acct_key(acct: dict[str, Any], index: int) -> str:
    return str(acct.get('id') or ('main' if index == 0 else f'acct{index + 1}'))


def _acct_label(acct: dict[str, Any], index: int) -> str:
    return str(acct.get('label') or ('主账号' if index == 0 else f'账号{index + 1}'))


def _sum_field(vals: list[str], prefix: str = '') -> str:
    nums = [n for n in (parse_num(v) for v in vals if v) if n is not None]
    return f'{prefix}{fmt_num(sum(nums))}' if nums else ''


def _aggregate_recs(recs: dict[str, dict], order: list[tuple[str, str]]) -> dict:
    """order: [(acct_id, label)] 凭证序 → 聚合展示字段（单账号原样透传）。"""
    seq = [(aid, label, recs[aid]) for aid, label in order if aid in recs]
    seq += [(aid, aid, rec) for aid, rec in recs.items()
            if aid not in {a for a, _, _ in seq}]
    if not seq:
        return {}
    if len(seq) == 1:
        return {**seq[0][2], 'account_note': ''}
    states = [r.get('state', '') for _, _, r in seq]
    if all(s in ('ok', 'already') for s in states):
        state = 'ok' if any(s == 'ok' for s in states) else 'already'
    elif any(s == 'error' for s in states):
        state = 'error'
    else:
        state = 'busy'
    n = len(seq)
    n_ok = sum(1 for s in states if s in ('ok', 'already'))
    word = ('全部完成' if all(s in ('ok', 'already') for s in states)
            else '部分失败' if any(s == 'error' for s in states) else '待重试')
    fails = [f'{label}：{r.get("message", "")}'
             for _, label, r in seq if r.get('state') == 'error']
    message = (f'{n_ok}/{n} 账号{word}'
               + (f'（{"；".join(fails)[:100]}）' if fails else ''))
    main_rec = next((r for a, _, r in seq if a == 'main'), seq[0][2])
    return {
        'state': state, 'message': message,
        'reward': _sum_field([r.get('reward', '') for _, _, r in seq], '+')
                  + (' 积分' if any('积分' in r.get('reward', '')
                                    for _, _, r in seq) else ''),
        'balance': _sum_field([r.get('balance', '') for _, _, r in seq]),
        'expiring': earliest_of([r.get('expiring', '') for _, _, r in seq]),
        'streak': main_rec.get('streak', 0),
        'keepalive': min([r.get('keepalive', '') for _, _, r in seq
                          if r.get('keepalive')], default=''),
        'at': max((r.get('at', '') for _, _, r in seq), default=''),
        'account_note': f'{n} 账号',
    }


def collect_status(cfg, store: CredentialStore, state: DailyState,
                   platforms: list[str]) -> dict[str, Any]:
    today = dt.date.today().isoformat()
    items = []
    done = 0
    for platform in platforms:
        adapter = get_adapter(platform)
        accounts = store.load_all(platform)
        order = [(_acct_key(a, i), _acct_label(a, i))
                 for i, a in enumerate(accounts)]
        recs = state.recs(platform, today)
        if order:      # 有凭证才按 id 集过滤，剔除已删账号的幽灵记录
            valid = {aid for aid, _ in order}
            recs = {k: v for k, v in recs.items() if k in valid}
        rec = _aggregate_recs(recs, order)
        if rec.get('state') in ('ok', 'already'):
            done += 1
        credential = '已导入' if accounts else '未导入凭证'
        cred_warn = False
        cred_notes: dict[str, str] = {}
        for i, acct in enumerate(accounts):
            report = store.expiry_report(platform, acct, adapter)
            parts = []
            if report.get('expired'):
                parts.append('已失效 ⚠')
            elif report.get('likely_expired_soon'):
                parts.append('临期 ⚠')
            elif report.get('expires_at'):
                parts.append(f'有效至 {report["expires_at"]}')
            saved = str(acct.get('saved_at') or '')[:10]
            if saved:
                parts.append(f'存于 {saved[5:]}')
            cred_notes[_acct_key(acct, i)] = ' · '.join(parts)
            if report.get('expired') or report.get('likely_expired_soon'):
                cred_warn = True
        if len(accounts) > 1:
            credential = f'已导入·{len(accounts)}号'
        items.append({
            'platform': platform, 'title': adapter.title,
            'state': rec.get('state', ''), 'message': rec.get('message', ''),
            'reward': rec.get('reward', ''), 'balance': rec.get('balance', ''),
            'streak': rec.get('streak', 0),
            'expiring': rec.get('expiring', ''),
            'account_note': rec.get('account_note', ''),
            'cred_warn': cred_warn,
            'accounts': [{'id': aid, 'label': label,
                          'cred_note': cred_notes.get(aid, ''),
                          **recs.get(aid, {})}
                         for aid, label in order],
            'keepalive': rec.get('keepalive', ''),
            'last_done': _last_done(state, platform, today),
            'credential': credential,
        })
    return {'today': today, 'done': done, 'total': len(items), 'platforms': items}


def collect_detail(store: CredentialStore, state: DailyState,
                   platform: str) -> dict[str, Any]:
    """卡片详情：逐账号积分明细（官方提供时），否则回退说明。"""
    adapter = get_adapter(platform)
    today = dt.date.today().isoformat()
    out: dict[str, Any] = {
        'ok': True, 'title': adapter.title, 'rows': [], 'note': '', 'accounts': [],
        'accent': _ACCENTS.get(platform, '#6b7280'),
        'balance': '', 'reward': ''}
    accounts = store.load_all(platform)
    if not accounts:
        out.update(ok=False, note='未导入凭证')
        return out
    recs = state.recs(platform, today)
    balances = []
    for i, acct in enumerate(accounts):
        aid = _acct_key(acct, i)
        g: dict[str, Any] = {'id': aid, 'label': _acct_label(acct, i),
                             'rows': [], 'note': ''}
        try:
            rows = adapter.breakdown(acct)
            if rows is None:
                g['note'] = '该平台官方接口不提供积分流水明细，余额见卡片'
            else:
                g['rows'] = rows
        except Exception as exc:                    # noqa: BLE001 —— 弹窗兜底
            g['note'] = f'查询失败：{type(exc).__name__} {str(exc)[:80]}'
        bal = (recs.get(aid) or {}).get('balance', '')
        if bal:
            balances.append(bal)
        out['accounts'].append(g)
    if len(accounts) == 1:
        out['rows'] = out['accounts'][0]['rows']
        out['note'] = out['accounts'][0]['note']
    nums = [n for n in (parse_num(b) for b in balances) if n is not None]
    out['balance'] = fmt_num(sum(nums)) if nums else ''
    return out


def _rows(p: dict[str, Any]) -> str:
    rows = [('今日已得', p['reward'] or '—'),
            ('余额', p['balance'] or '—'),
            ('最快到期', p['expiring'] or '—'),
            ('连续签到', f"{p['streak']} 天" if p['streak'] else '—'),
            ('上次签到', p['last_done'] or '—'),
            ('保活', p['keepalive'] or '—')]
    if p['state'] in ('error', 'busy') and p['message']:
        rows.append(('失败原因' if p['state'] == 'error' else '说明',
                     p['message']))
    return '\n'.join(
        f'<div class="kv"><span>{k}</span>'
        f'<span>{html_mod.escape(str(v))}</span></div>' for k, v in rows)


def _card(p: dict[str, Any]) -> str:
    accent = _ACCENTS.get(p['platform'], '#6b7280')
    text, bg, fg = _PILL.get(p['state'], _PILL[''])
    if p.get('account_note') and p['state'] in ('ok', 'already'):
        text += f"·{p['account_note'].split()[0]}号"
    big = p['reward'] or {'busy': '待重试', 'error': '失败',
                          '': '未执行'}.get(p['state'], '已签到')
    missing = p['credential'] not in ('已导入',) \
        and not p['credential'].startswith('已导入·')
    if missing:
        text, bg, fg = p['credential'], '#f3f4f6', '#6b7280'
        big = '未导入凭证'
    initial = p['title'][:1]
    if missing:
        btn = ('<a class="btn gray" href="/settings" '
               'onclick="event.stopPropagation()">导入凭证</a>')
    elif p['state'] in ('ok', 'already'):
        btn = '<button class="btn gray" disabled>今日已签到</button>'
    else:
        btn = (f'<button class="btn blue" onclick="event.stopPropagation();'
               f'doCheckin(\'{p["platform"]}\')">立即签到</button>')
    return (
        f'<div class="card clickable" onclick="showDetail(\'{p["platform"]}\')">'
        f'<div class="row"><span class="icon" style="background:{accent}1a;color:{accent}">'
        f'{initial}</span><span class="name">{html_mod.escape(p["title"])}</span>'
        f'<span class="pill" style="background:{bg};color:{fg}">{text}</span></div>'
        f'<div class="big" style="color:{accent}">{html_mod.escape(str(big))}</div>'
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
.card.clickable { cursor:pointer; }
.mask { position:fixed; inset:0; background:rgba(17,24,39,.35); display:none;
        align-items:center; justify-content:center; z-index:50; }
.modal { background:#fff; border-radius:14px; width:min(430px,92vw);
         max-height:72vh; overflow:auto; padding:18px 20px;
         box-shadow:0 8px 30px rgba(0,0,0,.18); }
.mhead { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.mtitle { font-size:16px; font-weight:700; flex:1; }
.mbal { font-size:12px; color:#6b7280; }
.mclose { color:#9ca3af; font-size:16px; cursor:pointer; padding:0 4px; }
.mtag { font-size:11px; border-radius:7px; padding:2px 7px; text-align:center; }
.mrow { display:grid; grid-template-columns:52px 1fr 72px 132px; gap:8px;
        align-items:center; padding:9px 2px;
        border-bottom:1px solid #f1f2f4; font-size:13px; color:#374151; }
.mrow .amt { text-align:right; font-weight:600; color:#111827; }
.mrow .exp { color:#6b7280; font-size:12px; text-align:right; }
.mnote { font-size:13px; color:#6b7280; padding:14px 2px; text-align:center; }
.mtabs { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
.mtab { border:1px solid #e5e7eb; background:#f8fafc; color:#6b7280; border-radius:9px;
        font-size:13px; padding:5px 14px; cursor:pointer; }
.mtab.on { background:#2563eb; border-color:#2563eb; color:#fff; font-weight:600; }
.mname { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.gear { font-size:17px; text-decoration:none; background:#eef0f3; border-radius:10px;
        width:38px; height:38px; display:flex; align-items:center; justify-content:center;
        color:#374151; flex:none; }
.gear:hover { background:#e2e5ea; }
.acct { background:#f8fafc; border:1px solid #eef0f3; border-radius:10px;
        padding:10px 12px; margin-top:10px; }
.arow { display:flex; align-items:center; gap:8px; }
.alabel { font-size:14px; font-weight:600; color:#111827; }
.ameta { font-size:12px; color:#6b7280; flex:1; }
.mini { border:1px solid #d1d5db; background:#fff; color:#374151; border-radius:7px;
        font-size:12px; padding:4px 10px; cursor:pointer; white-space:nowrap; }
.mini:hover { background:#f3f4f6; }
.mini.red { color:#dc2626; border-color:#fca5a5; }
.mini.red:hover { background:#fef2f2; }
.msum { display:flex; gap:10px; margin:0 0 12px; }
.msum span { flex:1; background:#f8fafc; border:1px solid #eef0f3; border-radius:10px;
             padding:8px 12px; font-size:15px; font-weight:600; color:#111827; }
.msum b { font-size:12px; font-weight:500; color:#6b7280; margin-right:6px; }
"""

_JS = r"""
async function doCheckin(p){
  const r = await fetch('/api/checkin/'+p,{method:'POST'});
  const j = await r.json();
  alert(j.ok ? ('签到结果：'+j.state+' '+j.message) : ('失败：'+j.message));
  location.reload();
}
async function saveCred(p,id){
  const body = {id};
  document.querySelectorAll('[data-p="'+p+'"][data-id="'+id+'"]').forEach(el => {
    if (el.value.trim()) body[el.dataset.field] = el.value.trim();
  });
  if (!body.cookie && !body.token) { alert('请先粘贴内容'); return; }
  const r = await fetch('/api/credentials/'+p,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j = await r.json();
  alert(j.ok ? '凭证已保存' : ('失败：'+j.message));
  if (j.ok) location.reload();
}
function toggleEdit(p,id){
  const el = document.getElementById('edit-'+p+'-'+id);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
function showNew(p){
  const el = document.getElementById('edit-'+p+'-new');
  el.style.display = 'block';
  el.scrollIntoView({behavior:'smooth', block:'center'});
}
async function delAcct(p,id){
  if (!confirm('删除该平台该账号的凭证？')) return;
  const r = await fetch('/api/credentials/'+p,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({clear:true,id})});
  const j = await r.json();
  alert(j.ok ? '已删除' : ('失败：'+j.message));
  location.reload();
}
function fmtNum(v){ return Number.isInteger(v) ? v.toLocaleString('zh-CN')
  : v.toFixed(2).replace(/\.00$/, ''); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
let _det = null, _detSeq = 0;
async function showDetail(p){
  const s = ++_detSeq;
  const r = await fetch('/api/detail/'+p);
  const j0 = await r.json();
  if (s !== _detSeq) return;            // 慢的旧响应不许覆盖新弹窗
  _det = j0;
  const j = _det, ac = j.accent || '#6b7280';
  let h = '<div class="mhead"><span class="icon" style="background:'+ac+'1a;color:'+ac+'">'
    + esc((j.title||'?').slice(0,1)) + '</span><span class="mtitle">' + esc(j.title)
    + '</span><span class="mbal">余额 ' + (j.balance ? esc(j.balance) : '—')
    + '</span><span class="mclose" onclick="closeDetail()">✕</span></div>';
  const groups = (j.accounts && j.accounts.length > 1) ? j.accounts
    : [{label:'', rows:j.rows||[], note:j.note||''}];
  if (groups.length > 1) {
    h += '<div class="mtabs">' + groups.map((g, i) =>
      '<button class="mtab" onclick="showGroup(' + i + ')">'
      + esc(g.label || ('账号' + (i + 1))) + '</button>').join('') + '</div>';
  }
  h += '<div id="mbody"></div>';
  document.getElementById('modal').innerHTML = h;
  document.getElementById('mask').style.display = 'flex';
  showGroup(0);
}
function showGroup(i){
  const j = _det, ac = j.accent || '#6b7280';
  const groups = (j.accounts && j.accounts.length > 1) ? j.accounts
    : [{label:'', rows:j.rows||[], note:j.note||''}];
  const g = groups[i] || {rows:[], note:'暂无明细'};
  document.querySelectorAll('.mtab').forEach((el, k) =>
    el.classList.toggle('on', k === i));
  let h = '';
  if (g.rows && g.rows.length) {
    const sums = {};
    g.rows.forEach(row => { const v = parseFloat(row.amount);
      if (!isNaN(v)) sums[row.tag] = (sums[row.tag] || 0) + v; });
    const keys = Object.keys(sums);
    if (keys.length > 1) h += '<div class="msum">' + keys.map(k =>
      '<span><b>' + esc(k) + '</b> ' + fmtNum(sums[k]) + '</span>').join('')
      + '</div>';
    h += g.rows.map(row => '<div class="mrow"><span class="mtag" style="background:'
      + ac + '1a;color:' + ac + '">' + esc(row.tag) + '</span><span class="mname" '
      + 'title="' + esc(row.name) + '">' + esc(row.name)
      + '</span><span class="amt">' + esc(row.amount) + '</span><span class="exp">'
      + esc(row.expire) + '</span></div>').join('');
  } else {
    h += '<div class="mnote">' + esc(g.note || '暂无明细') + '</div>';
  }
  document.getElementById('mbody').innerHTML = h;
}
function closeDetail(){ document.getElementById('mask').style.display = 'none'; }
"""


def render_html(status: dict[str, Any]) -> str:
    pct = int(status['done'] / status['total'] * 100) if status['total'] else 0
    cards = '\n'.join(_card(p) for p in status['platforms'])
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>签到中心</title><style>{_STYLE}</style><script>{_JS}</script></head>
<body><div class="wrap">
<div class="head"><div class="row"><div style="flex:1">
<div class="title">📋 签到中心</div>
<div class="slogan">多个签到一目了然 · 点击卡片查看积分明细</div></div>
<a class="gear" href="/settings" title="设置">⚙️</a></div>
<div class="bar"><div class="fill" style="width:{pct}%"></div></div>
<div class="meta"><span>今日签到进度 {status['today']}</span>
<span>已签 {status['done']} / {status['total']}</span></div></div>
<div class="grid">
{cards}
</div>
<div class="foot">所有签到均在服务端执行，数据来自各平台官方接口<br>
新增签到只需在服务端加一个适配器，本页自动多出一张卡 · v{__version__}</div>
</div>
<div class="mask" id="mask" onclick="if(event.target===this)closeDetail()">
<div class="modal" id="modal"></div></div>
</body></html>"""


def _cred_form(platform: str, aid: str, fields, label: str,
               save_text: str = '保存') -> str:
    """一个账号的凭证编辑表单（外层默认 display:none，点开关展开）。"""
    dom = '' if aid == 'main' else f'-{aid}'
    inputs = '\n'.join(
        f'<div class="slogan" style="margin:8px 0 4px">{html_mod.escape(ftxt)}</div>'
        f'<textarea id="cred-{platform}{dom}-{fname}" data-p="{platform}" '
        f'data-id="{aid}" data-field="{fname}" rows="3" '
        f'placeholder="粘贴后点击{save_text}" style="width:100%;box-sizing:border-box;'
        f'border:1px solid #d1d5db;border-radius:8px;padding:8px;font-size:12px"></textarea>'
        for fname, ftxt in fields)
    return (
        '<div class="row" style="margin-top:8px"><input data-p="' + platform + '" '
        'data-id="' + aid + '" data-field="label" placeholder="账号备注名（可选）" '
        'value="' + html_mod.escape(label, quote=True) + '" style="flex:1;border:1px '
        'solid #d1d5db;border-radius:8px;padding:6px 8px;font-size:13px"></div>'
        + inputs
        + '<button class="btn blue" style="margin-top:8px" '
          'onclick="saveCred(\'' + platform + '\',\'' + aid + '\')">'
        + save_text + '</button>')


def render_settings(status: dict[str, Any]) -> str:
    blocks = []
    for p in status['platforms']:
        fields = _CRED_FIELDS.get(p['platform'], [('cookie', 'Cookie 整串')])
        accent = _ACCENTS.get(p['platform'], '#6b7280')
        accounts = p.get('accounts') or [{'id': 'main', 'label': ''}]
        rows = []
        for a in accounts:
            aid = sanitize_acct_id(a.get('id')) or 'main'
            label = sanitize_label(a.get('label'))
            shown = label or ('主账号' if aid == 'main' else aid)
            del_btn = (
                '<button class="mini red" onclick="delAcct(\'' + p['platform']
                + '\',\'' + aid + '\')">删除</button>'
                if len(accounts) > 1 or aid != 'main' else '')
            rows.append(
                '<div class="acct"><div class="arow">'
                '<span class="alabel">' + html_mod.escape(shown) + '</span>'
                '<span class="ameta">'
                + html_mod.escape(a.get('cred_note') or '未导入') + '</span>'
                '<button class="mini" onclick="toggleEdit(\'' + p['platform']
                + '\',\'' + aid + '\')">更新凭证</button>' + del_btn + '</div>'
                '<div id="edit-' + p['platform'] + '-' + aid + '" '
                'style="display:none">'
                + _cred_form(p['platform'], aid, fields, label) + '</div></div>')
        blocks.append(
            '<div class="card">'
            '<div class="row"><span class="icon" style="background:' + accent
            + '1a;color:' + accent + '">' + p['title'][:1] + '</span>'
            '<span class="name">' + p['title'] + '</span>'
            '<span class="pill" style="background:#f3f4f6;color:#6b7280">'
            + p['credential']
            + (' ⚠' if p.get('cred_warn') else '') + '</span></div>'
            + '\n'.join(rows)
            + '<div id="edit-' + p['platform'] + '-new" style="display:none" '
            'class="acct">'
            + _cred_form(p['platform'], 'new', fields, '', '添加') + '</div>'
            + '<button class="btn gray" style="margin-top:10px" '
              'onclick="showNew(\'' + p['platform'] + '\')">+ 添加账号</button>'
            + '</div>')
    cards = '\n'.join(blocks)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>设置 · 签到中心</title><style>{_STYLE}</style><script>{_JS}</script></head>
<body><div class="wrap">
<div class="head"><div class="row"><div style="flex:1">
<div class="title">⚙️ 设置</div>
<div class="slogan">管理各平台账号凭证 · 数据仅存本机</div></div>
<a class="gear" href="/" title="返回签到中心">←</a></div></div>
<div class="grid">
{cards}
</div></div></body></html>"""


_BUSY: set[str] = set()
_BUSY_LOCK = threading.Lock()


def _begin_checkin(platform: str) -> bool:
    """同平台签到防重入:面板连点不再并发打官方接口。"""
    with _BUSY_LOCK:
        if platform in _BUSY:
            return False
        _BUSY.add(platform)
        return True


def _end_checkin(platform: str) -> None:
    with _BUSY_LOCK:
        _BUSY.discard(platform)


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
        cfg, store, state, status = self._status()
        if self.path.startswith('/api/status'):
            self._json(status)
        elif self.path.startswith('/api/detail/'):
            platform = self.path.rpartition('/')[2]
            if platform not in ADAPTERS:
                self._json({'ok': False, 'note': f'未知平台 {platform}'}, 404)
            else:
                self._json(collect_detail(store, state, platform))
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
        ctype = (self.headers.get('Content-Type') or '').lower()
        if 'application/json' not in ctype:
            self._json({'ok': False, 'message': '需要 application/json'}, 415)
            return
        cfg, store, state, _ = self._status()
        length = min(int(self.headers.get('Content-Length') or 0), 1024 * 1024)
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except Exception:
            payload = {}
        kind, _, platform = self.path.rpartition('/')
        head = kind.rstrip('/')
        if platform not in ADAPTERS:
            self._json({'ok': False, 'message': f'未知平台 {platform}'}, 404)
            return
        if head.endswith('/api/credentials'):
            if payload.get('clear'):
                acct_id = payload.get('id')
                if acct_id:
                    store.remove(platform, acct_id)
                    self._json({'ok': True, 'message': '已删除该账号'})
                else:
                    self._json({'ok': True, **store.clear(platform)})
                return
            fields = {k: v for k, v in payload.items()
                      if v not in ('', None) and k != 'id'}
            acct_id = payload.get('id')
            if not (fields.get('cookie') or fields.get('token')):
                ok_label = acct_id and fields.get('label') and                     len(fields) == 1
                if not ok_label:
                    self._json({'ok': False, 'message': '需提供 cookie 或 token 字段'})
                    return
            if acct_id and str(acct_id).startswith('new'):
                acct_id = None            # 前端占位 id：由服务端按凭证哈希建号
            store.upsert(platform, fields, acct_id=acct_id)
            self._json({'ok': True, 'message': '已导入'})
        elif head.endswith('/api/checkin'):
            if not _begin_checkin(platform):
                self._json({'ok': False, 'message': '该平台正在签到中'}, 409)
                return
            try:
                from app.main import cmd_run_once
                outcomes = cmd_run_once(cfg, platforms=[platform], store=store,
                                        state=state, notifier=_NoopNotifier())
                r = outcomes[0].result
                self._json({'ok': r.state in ('ok', 'already'),
                            'state': r.state, 'message': r.message})
            finally:
                _end_checkin(platform)
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
