# -*- coding: utf-8 -*-
"""PC 端一键：提取本机全部账号凭证 → 推送到 NAS 面板。

用法：双击 推送凭证.bat，或
    python tools/push_panel.py [--list] [--all] [--no-wb] [--url http://host:8000]

来源规则：
- 默认：wb-switch 账号文件全部账号 + 桌面端直读 + inbox 补充。
- --no-wb：完全不碰 wb-switch——Trae/WorkBuddy 桌面端直读，
  其余平台用 inbox（login --headful 抓的浏览器 Cookie / 手动粘贴存档）。
- 每平台第一个作为主账号（id=main，token 轮换原位刷新）；同账号多票
  按 JWT uid 归并取到期最远；其余按 label/凭证在面板侧去重，不会裂号。
- 默认只推"本次扫到 + inbox 7 天内更新过"的，--all 忽略新鲜度。
凭证只 POST 不打印。
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.platforms import ADAPTERS  # noqa: E402
from app.scanner import (_COOKIE_PLATFORMS, _KEY_ALIASES, _SUPPORTED,  # noqa: E402
                         scan_local_accounts)

DEFAULT_URL = os.environ.get('PANEL_URL', 'http://nas.zeln.top:8000')
MAX_AGE_DAYS = 7
FIELDS = ('cookie', 'token', 'csrf', 'uid', 'device_id', 'enterprise_id',
          'domain', 'region', 'host', 'user_id', 'web_session', 'label')

# Trae 桌面端 storage.json 解密（算法与常量逐字移植自 agent-auto-signin）
_TABLE_A = bytes([82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
                  124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
                  84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
                  8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37])
_TABLE_B = bytes([31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
                  96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
                  160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
                  23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125])


def _inbox() -> Path:
    return Path(os.environ.get('DATA_DIR', '/data')) / 'inbox'


def _wb_switch_accounts() -> dict:
    """{platform: [body, ...]}，保留 wb-switch 里的全部账号顺序。"""
    f = Path.home() / '.wb-switch' / 'agent_accounts.json'
    out = {}
    if not f.exists():
        return out
    try:
        accounts = json.loads(f.read_text(encoding='utf-8'))
    except Exception:
        return out
    for acc in accounts if isinstance(accounts, list) else []:
        if not isinstance(acc, dict):
            continue
        p = _KEY_ALIASES.get(acc.get('platform'), acc.get('platform'))
        tok = str(acc.get('token') or '')
        if p not in _SUPPORTED or not tok or acc.get('needs_relogin'):
            continue
        body = ({'cookie': tok} if p in _COOKIE_PLATFORMS
                else {'token': tok})
        if acc.get('device_id'):
            body['device_id'] = str(acc['device_id'])
        if acc.get('name'):
            body['label'] = str(acc['name'])[:20]
        out.setdefault(p, []).append(body)
    return out


def _jwt_ident(body: dict):
    """JWT 票的 (uid, exp)：同一账号在不同来源的多张票按 uid 归并。"""
    tok = str(body.get('token') or '')
    if tok.count('.') < 2:
        return None, 0
    try:
        seg = tok.split('.')[1]
        seg += '=' * (-len(seg) % 4)
        p = json.loads(base64.urlsafe_b64decode(seg))
        return (str(p.get('sub') or p.get('uid') or p.get('id') or '') or None,
                int(p.get('exp') or 0))
    except Exception:
        return None, 0


def _extract_trae_desktop():
    """Trae 桌面端直读：解密 storage.json 的 iCubeAuthInfo 拿当前登录 token。"""
    appdata = os.environ.get('APPDATA', '')
    if not appdata:
        return None
    storage = Path(appdata) / 'TRAE SOLO CN' / 'User' / 'globalStorage' \
        / 'storage.json'
    if not storage.exists():
        return None
    try:
        enc = json.loads(storage.read_text(encoding='utf-8')).get(
            'iCubeAuthInfo://icube.cloudide')
        if not enc:
            return None
        blob = base64.b64decode(enc)
        sha = hashlib.sha512(blob[6:38]).digest()
        xor = bytes(a ^ b for a, b in zip(_TABLE_A, _TABLE_B))
        h = hashlib.sha512(sha + xor).digest()
        proc = subprocess.run(
            ['openssl', 'enc', '-d', '-aes-128-cbc', '-nopad',
             '-K', h[:16].hex(), '-iv', h[16:32].hex()],
            input=blob[38:], capture_output=True, timeout=10)
        if proc.returncode != 0:
            return None
        pt = proc.stdout
        pt = pt[:-pt[-1]]
        auth = json.loads(pt[64:].decode('utf-8', errors='replace'))
        if not auth.get('token'):
            return None
        body = {'token': str(auth['token']), 'label': 'Trae桌面'}
        region = auth.get('userRegion')
        if isinstance(region, dict) and region.get('region'):
            body['region'] = str(region['region'])
        if auth.get('host'):
            body['host'] = str(auth['host']).rstrip('/')
        return body
    except Exception:
        return None


def _collect(inbox: Path, push_all: bool, no_wb: bool = False) -> list:
    by_plat = {}
    if no_wb:
        fresh = set()
        from app.scanner import _read_workbuddy_auth
        wb = _read_workbuddy_auth(None, None, Path.home())
        if wb:
            by_plat.setdefault('workbuddy', []).append(wb)
    else:
        fresh = set(scan_local_accounts(inbox))
        by_plat = _wb_switch_accounts()
    trae = _extract_trae_desktop()   # 桌面当前登录态，永远最优先
    if trae:
        by_plat.setdefault('trae', []).insert(0, trae)
    inbox_bodies = {}
    # .json 与近 7 天 .json.imported（本机导入后改名的存档）都可再推
    for path in sorted(inbox.glob('*.json')) + sorted(
            inbox.glob('*.json.imported')):
        platform = path.name.split('.')[0]
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if not push_all and platform not in fresh and age_days > MAX_AGE_DAYS:
            print(f'  跳过 {platform}（inbox 已 {age_days:.0f} 天未更新，'
                  f'--all 可强推）')
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        body = {k: v for k, v in data.items() if k in FIELDS and v}
        if body.get('cookie') or body.get('token'):
            inbox_bodies[platform] = body
    items = []
    for p in sorted(set(by_plat) | set(inbox_bodies)):
        if p not in ADAPTERS:
            print(f'  跳过 {p}（面板已下架该平台）')
            continue
        groups = {}   # 身份键 -> (exp, body)；同账号多票取到期最远那张
        cands = list(by_plat.get(p, []))
        if p in inbox_bodies:
            cands.append(inbox_bodies[p])
        for body in cands:
            prim = body.get('token') or body.get('cookie')
            if not prim:
                continue
            uid, exp = _jwt_ident(body)
            key = uid or prim
            if key in groups:
                old_exp, old = groups[key]
                if not body.get('label') and old.get('label'):
                    body['label'] = old['label']
                groups[key] = (max(exp, old_exp), body) if exp >= old_exp \
                    else (old_exp, old)
            else:
                groups[key] = (exp, body)
        for i, (exp, body) in enumerate(groups.values()):
            if not _jwt_ident(body)[0]:
                # 无 JWT uid 可辨身份：Cookie 平台一律视为面板主账号，
                # 绝不允许按票哈希裂出副账号（2026-09-25 搭子裂号事故）
                body['id'] = 'main'
            items.append((p, body))
    return items


def _panel_state(url: str) -> dict:
    """拉面板现状：{platform: [{id, hash, uid}]}，用于身份路由。"""
    req = urllib.request.Request(f'{url}/api/status',
                                 headers={'X-Panel-Token': _token()})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode('utf-8'))
        return {p.get('platform'): p.get('accounts', [])
                for p in data.get('platforms', [])}
    except Exception:
        return {}


def _body_hashes(body: dict) -> set:
    out = set()
    for k in ('token', 'cookie'):
        v = str(body.get(k) or '')
        if v:
            out.add(hashlib.sha1(v.encode('utf-8')).hexdigest()[:8])
    return out


def _route_id(p: str, body: dict, panel: dict) -> str | None:
    """任一凭证字段哈希同→原账号；JWT uid 同→原账号(换票)；空→main；否则新增。"""
    accs = [a for a in panel.get(p, []) if isinstance(a, dict)]
    if accs and not any('hashes' in a for a in accs):
        return 'main'      # 旧面板无指纹字段：保守只更新主账号
    hs = _body_hashes(body)
    for a in accs:
        if hs & set(a.get('hashes') or []):
            return a.get('id')
    uid = _jwt_ident(body)[0]
    if uid:
        for a in accs:
            if a.get('uid') == uid:
                return a.get('id')
    return 'main' if not accs else None


def _token() -> str:
    f = Path(__file__).with_name('.panel_token')
    tok = os.environ.get('PANEL_TOKEN', '').strip()
    if not tok and f.exists():
        tok = f.read_text(encoding='utf-8').strip()
    return tok


def _push(url: str, platform: str, body: dict) -> str:
    headers = {'Content-Type': 'application/json'}
    tok = _token()
    if tok:
        headers['X-Panel-Token'] = tok
    req = urllib.request.Request(
        f'{url}/api/credentials/{platform}',
        data=json.dumps(body).encode('utf-8'),
        headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode('utf-8'))
        return 'OK' if resp.get('ok') else f"失败: {resp.get('message')}"
    except Exception as exc:
        return f'失败: {type(exc).__name__}'


def _headful_login(csv_platforms: str) -> None:
    """推送前先刷新浏览器凭证：storage_state 有效则静默抓新 Cookie，
    失效才弹浏览器让本机登录一次。"""
    from app.browser_login import browser_login
    from app.config import Config
    cfg = Config((10, 5), 3, '', _inbox().parent)
    for p in csv_platforms.split(','):
        p = p.strip()
        if not p:
            continue
        print(f'登录刷新 {p}（会话有效则无感，需登录会弹浏览器）…')
        code = browser_login(cfg, p, headful=True)
        print(f'  {p}: {"OK" if code == 0 else f"退出码 {code}"}')


def main() -> int:
    args = sys.argv[1:]
    url = DEFAULT_URL.rstrip('/')
    if '--url' in args:
        url = args[args.index('--url') + 1].rstrip('/')
    if '--login' in args:
        _headful_login(args[args.index('--login') + 1])
    items = _collect(_inbox(), '--all' in args, '--no-wb' in args)
    if not items:
        print('没有可推送的凭证。可先运行：python -m app.main login <平台> --headful')
        return 1
    print(f'目标面板：{url}')
    panel = _panel_state(url)
    if not panel:
        if '--list' in args:
            print('拉取面板账号状态失败（网络/密码？），以下路由结果不准确')
        else:
            print('拉取面板账号状态失败（网络/密码？），中止推送防止重复建号')
            return 1
    bad = 0
    for platform, body in items:
        rid = _route_id(platform, body, panel)
        if rid:
            body['id'] = rid
        label = body.get('label')
        tag = f"{platform}({label})" if label else platform
        dest = rid or body.get('id') or '新增账号'
        if '--list' in args:
            print(f'  {tag}: 待推送 → {dest}')
            continue
        result = _push(url, platform, body)
        print(f'  {tag} → {dest}: {result}')
        bad += result != 'OK'
    return 1 if bad and '--list' not in args else 0


if __name__ == '__main__':
    sys.exit(main())
