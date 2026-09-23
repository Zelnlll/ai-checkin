import json
from pathlib import Path

from app.scanner import scan_local_accounts


def _fake_home(tmp_path):
    home = tmp_path / 'home'
    wbs = home / '.wb-switch'
    wbs.mkdir(parents=True)
    accounts = [
        {'platform': 'wps', 'token': 'wps_sid=abc; other=1', 'needs_relogin': False},
        {'platform': 'qoder', 'token': 'dt-token-1', 'needs_relogin': False},
        {'platform': 'linkai', 'token': 'eyJx', 'needs_relogin': False},   # 现已支持
        {'platform': 'minimax', 'token': '', 'needs_relogin': False},      # 空→忽略
        {'platform': 'dazi', 'token': 'ck', 'needs_relogin': True},        # 待重登→忽略
    ]
    (wbs / 'agent_accounts.json').write_text(json.dumps(accounts), encoding='utf-8')
    (wbs / 'modelscope_login.json').write_text(
        json.dumps({'cookie': 'm_session_id=x; t=y'}), encoding='utf-8')
    return home


def test_scan_imports_supported_platforms(tmp_path):
    inbox = tmp_path / 'inbox'
    found = scan_local_accounts(inbox, home=_fake_home(tmp_path),
                                  appdata=tmp_path / 'noapp')
    assert sorted(found) == ['linkai', 'modelscope', 'qoder', 'wps']
    wps = json.loads((inbox / 'wps.json').read_text(encoding='utf-8'))
    assert wps == {'cookie': 'wps_sid=abc; other=1'}          # cookie 平台归 cookie 字段
    qoder = json.loads((inbox / 'qoder.json').read_text(encoding='utf-8'))
    assert qoder == {'token': 'dt-token-1'}
    ms = json.loads((inbox / 'modelscope.json').read_text(encoding='utf-8'))
    assert ms['cookie'].startswith('m_session_id')


def test_scan_no_home_files(tmp_path):
    inbox = tmp_path / 'inbox'
    assert scan_local_accounts(inbox, home=tmp_path / 'nobody',
                               appdata=tmp_path / 'noapp') == []
    assert not (inbox / 'wps.json').exists()


def test_scan_result_is_importable(tmp_path):
    from app.credentials import CredentialStore
    inbox = tmp_path / 'data' / 'inbox'
    scan_local_accounts(inbox, home=_fake_home(tmp_path))
    store = CredentialStore(tmp_path / 'data', {'wps', 'qoder', 'modelscope'})
    imported = dict(store.import_inbox())
    assert sorted(imported) == ['modelscope', 'qoder', 'wps']


def test_scan_maps_dumate_key_to_dazi(tmp_path):
    home = tmp_path / 'home'
    wbs = home / '.wb-switch'
    wbs.mkdir(parents=True)
    (wbs / 'agent_accounts.json').write_text(json.dumps(
        [{'platform': 'dumate', 'token': 'bce-user-info=x', 'needs_relogin': False}]),
        encoding='utf-8')
    inbox = tmp_path / 'inbox'
    assert scan_local_accounts(inbox, home=home, appdata=tmp_path / 'noapp') == ['dazi']
    assert json.loads((inbox / 'dazi.json').read_text(encoding='utf-8'))['cookie'] == 'bce-user-info=x'


def test_scan_trae_and_workbuddy(tmp_path):
    home = tmp_path / 'home'
    wbs = home / '.wb-switch'
    wbs.mkdir(parents=True)
    (wbs / 'agent_accounts.json').write_text(json.dumps(
        [{'platform': 'trae', 'token': 'CJT', 'device_id': 'D1',
          'needs_relogin': False}]), encoding='utf-8')
    local = tmp_path / 'local'
    auth_dir = local / 'CodeBuddyExtension' / 'Data' / 'Public' / 'auth'
    auth_dir.mkdir(parents=True)
    (auth_dir / 'workbuddy-desktop.info').write_text(json.dumps(
        {'auth': {'accessToken': 'AT', 'domain': 'tencent.com'},
         'account': {'uid': 'U9', 'enterpriseId': 'E1'}}), encoding='utf-8')
    inbox = tmp_path / 'inbox'
    found = scan_local_accounts(inbox, home=home, appdata=tmp_path / 'noapp',
                                localappdata=local)
    assert found == ['trae', 'workbuddy']
    assert json.loads((inbox / 'trae.json').read_text(encoding='utf-8')) == \
        {'token': 'CJT', 'device_id': 'D1'}
    assert json.loads((inbox / 'workbuddy.json').read_text(encoding='utf-8')) == \
        {'token': 'AT', 'uid': 'U9', 'domain': 'tencent.com', 'enterprise_id': 'E1'}


def test_scan_linkai_from_agent_accounts(tmp_path):
    home = tmp_path / 'home'
    wbs = home / '.wb-switch'
    wbs.mkdir(parents=True)
    (wbs / 'agent_accounts.json').write_text(json.dumps(
        [{'platform': 'linkai', 'token': 'eyJbrowser', 'needs_relogin': False}]),
        encoding='utf-8')
    inbox = tmp_path / 'inbox'
    assert scan_local_accounts(inbox, home=home, appdata=tmp_path / 'noapp') == ['linkai']
    assert json.loads((inbox / 'linkai.json').read_text())['token'] == 'eyJbrowser'


def test_scan_linkai_desktop_leveldb_wins(tmp_path):
    """桌面客户端 leveldb 的完整 JWT 覆盖 agent_accounts 里的浏览器残缺版。"""
    home = tmp_path / 'home'
    (home / '.wb-switch').mkdir(parents=True)
    (home / '.wb-switch' / 'agent_accounts.json').write_text(json.dumps(
        [{'platform': 'linkai', 'token': 'eyJshort', 'needs_relogin': False}]),
        encoding='utf-8')
    good = 'eyJ' + 'A' * 200
    ldb = home / 'AppData' / 'LinkAI' / 'Local Storage' / 'leveldb'
    ldb.mkdir(parents=True)
    (ldb / '000003.log').write_bytes(b'linkai_jwt' + good.encode() + b'\x00\x01junk')
    inbox = tmp_path / 'inbox'
    found = scan_local_accounts(inbox, home=home,
                                appdata=home / 'AppData')
    assert 'linkai' in found
    assert json.loads((inbox / 'linkai.json').read_text())['token'] == good
