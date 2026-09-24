"""扫描本机（服务运行机器）已捕获的平台凭证 → 写入 inbox。

来源：~/.wb-switch/agent_accounts.json（wb-switch 捕获的各家 token/cookie 混存字段）、
~/.wb-switch/modelscope_login.json（魔搭会话）。仅导入本项目支持的平台。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_COOKIE_PLATFORMS = {'wps', 'dazi'}
# wb-switch 存储键 → 本项目平台键（agent_ext.rs 里搭子的 key 是 dumate）
_KEY_ALIASES = {'dumate': 'dazi'}
_SUPPORTED = {'wps', 'dazi', 'minimax', 'qoder', 'trae'}


def scan_local_accounts(inbox: Path, home: Path | None = None,
                        appdata: Path | None = None,
                        localappdata: Path | None = None) -> list[str]:
    home = home or Path.home()
    inbox = Path(inbox)
    found: list[str] = []
    accounts_file = home / '.wb-switch' / 'agent_accounts.json'
    if accounts_file.exists():
        try:
            accounts = json.loads(accounts_file.read_text(encoding='utf-8'))
        except Exception:
            accounts = []
        for acc in accounts if isinstance(accounts, list) else []:
            platform = acc.get('platform') if isinstance(acc, dict) else None
            platform = _KEY_ALIASES.get(platform, platform)
            token = str(acc.get('token') or '') if isinstance(acc, dict) else ''
            if platform not in _SUPPORTED or not token or acc.get('needs_relogin'):
                continue
            creds = {'cookie': token} if platform in _COOKIE_PLATFORMS else {'token': token}
            if platform == 'trae' and acc.get('device_id'):
                creds['device_id'] = str(acc['device_id'])
            found.append(_write(inbox, platform, creds))
    ms_file = home / '.wb-switch' / 'modelscope_login.json'
    if ms_file.exists():
        try:
            data = json.loads(ms_file.read_text(encoding='utf-8'))
        except Exception:
            data = {}
        cookie = str(data.get('cookie') or '')
        if 'm_session_id' in cookie:
            creds = {'cookie': cookie}
            sdk = str(data.get('token') or data.get('sdk_token') or '')
            if sdk.startswith('ms-'):
                creds['token'] = sdk
            found.append(_write(inbox, 'modelscope', creds))
    wb = _read_workbuddy_auth(localappdata, appdata, home)
    if wb:
        _write(inbox, 'workbuddy', wb)
        found.append('workbuddy')
    return sorted(found)


def _read_workbuddy_auth(localappdata: Path | None, appdata: Path | None,
                         home: Path) -> dict:
    if localappdata:
        local = Path(localappdata)
    elif appdata:
        local = Path(appdata).parent / 'Local'
    else:
        local = Path(os.environ.get('LOCALAPPDATA')
                     or home / 'AppData' / 'Local')
    candidates = [
        local / 'CodeBuddyExtension' / 'Data' / 'Public' / 'auth'
        / 'workbuddy-desktop.info',
        home / '.workbuddy' / 'auth' / 'workbuddy-desktop.info',
    ]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        auth = data.get('auth') or {}
        account = data.get('account') or {}
        token, uid = str(auth.get('accessToken') or ''), str(account.get('uid') or '')
        if not token or not uid:
            continue
        creds = {'token': token, 'uid': uid}
        if auth.get('domain'):
            creds['domain'] = str(auth['domain'])
        if account.get('enterpriseId'):
            creds['enterprise_id'] = str(account['enterpriseId'])
        return creds
    return {}


def _write(inbox: Path, platform: str, creds: dict) -> str:
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / f'{platform}.json').write_text(
        json.dumps(creds, ensure_ascii=False), encoding='utf-8')
    return platform
