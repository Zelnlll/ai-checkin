"""签到结果 → 仪表盘风格 HTML（仿用户截图：进度条 + 彩色描边卡片墙）。"""

from __future__ import annotations

from html import escape
from typing import Any

from app.platforms import get_adapter
from app.scheduler import CheckinOutcome

_ACCENTS = {
    'wps': '#22b14c', 'dazi': '#3b82f6', 'minimax': '#8b5cf6',
    'qoder': '#111827', 'modelscope': '#f59e0b',
}
_DEFAULT_ACCENT = '#6b7280'

_PILL = {
    'ok': ('今天已签到 ✅', '#e7f7ec', '#16a34a'),
    'already': ('已签到 ✔', '#eef2ff', '#4f46e5'),
    'busy': ('待重试 ⏳', '#fef9c3', '#a16207'),
    'error': ('失败 ❌', '#fee2e2', '#dc2626'),
}


def _big_number(o: CheckinOutcome) -> str:
    r = o.result
    if r.reward:
        return r.reward
    return {'ok': '成功', 'already': '已签到', 'busy': '待重试', 'error': '—'}.get(r.state, '—')


def _card(o: CheckinOutcome) -> str:
    try:
        title = get_adapter(o.platform).title
    except KeyError:
        title = o.platform
    accent = _ACCENTS.get(o.platform, _DEFAULT_ACCENT)
    pill_text, pill_bg, pill_fg = _PILL.get(o.result.state, ('未知', '#f3f4f6', '#374151'))
    pill_cls = 'status-error' if o.result.state == 'error' else 'status-ok'
    sub = escape(o.result.message)[:40]
    return (
        f'<div class="card" style="border-top-color:{accent}">'
        f'<div class="row"><span class="dot" style="background:{accent}"></span>'
        f'<span class="name">{escape(title)}</span>'
        f'<span class="pill {pill_cls}" style="background:{pill_bg};color:{pill_fg}">{pill_text}</span></div>'
        f'<div class="big" style="color:{accent}">{escape(_big_number(o))}</div>'
        f'<div class="sub">{sub}</div></div>'
    )


def build_report_html(outcomes: list[CheckinOutcome], today: str) -> str:
    total = len(outcomes)
    done = sum(1 for o in outcomes if o.result.done())
    pct = int(done / total * 100) if total else 0
    cards = '\n'.join(_card(o) for o in outcomes)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ margin:0; padding:28px; background:#f3f6f9; width:860px;
       font-family:'Microsoft YaHei','PingFang SC',sans-serif; }}
.head {{ background:#fff; border-radius:14px; padding:18px 24px; margin-bottom:18px;
        box-shadow:0 1px 4px rgba(0,0,0,.06); }}
.title {{ font-size:22px; font-weight:700; color:#111827; }}
.slogan {{ font-size:13px; color:#6b7280; margin-top:4px; }}
.bar {{ height:10px; background:#e5e7eb; border-radius:5px; margin-top:14px; overflow:hidden; }}
.fill {{ height:100%; background:linear-gradient(90deg,#34d399,#10b981); width:{pct}%; }}
.meta {{ display:flex; justify-content:space-between; font-size:14px; color:#374151; margin-top:8px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:16px; }}
.card {{ background:#fff; border-radius:12px; border-top:4px solid #666;
        padding:16px 18px; box-shadow:0 1px 4px rgba(0,0,0,.05); }}
.row {{ display:flex; align-items:center; gap:8px; }}
.dot {{ width:12px; height:12px; border-radius:4px; display:inline-block; }}
.name {{ font-size:16px; font-weight:600; color:#1f2937; flex:1; }}
.pill {{ font-size:12px; border-radius:10px; padding:2px 8px; }}
.big {{ font-size:30px; font-weight:800; margin:12px 0 6px; }}
.sub {{ font-size:12px; color:#6b7280; min-height:16px; }}
</style></head><body>
<div class="head">
  <div class="title">📋 签到中心</div>
  <div class="slogan">多个签到 · 一目了然</div>
  <div class="bar"><div class="fill"></div></div>
  <div class="meta"><span>今日签到进度 {escape(today)}</span><span>已签 {done} / {total}</span></div>
</div>
<div class="grid">
{cards}
</div>
</body></html>"""
