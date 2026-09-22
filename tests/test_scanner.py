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
        {'platform': 'linkai', 'token': 'x', 'needs_relogin': False},      # 不支持→忽略
        {'platform': 'minimax', 'token': '', 'needs_relogin': False},      # 空→忽略
        {'platform': 'dazi', 'token': 'ck', 'needs_relogin': True},        # 待重登→忽略
    ]
    (wbs / 'agent_accounts.json').write_text(json.dumps(accounts), encoding='utf-8')
    (wbs / 'modelscope_login.json').write_text(
        json.dumps({'cookie': 'm_session_id=x; t=y'}), encoding='utf-8')
    return home


def test_scan_imports_supported_platforms(tmp_path):
    inbox = tmp_path / 'inbox'
    found = scan_local_accounts(inbox, home=_fake_home(tmp_path))
    assert sorted(found) == ['modelscope', 'qoder', 'wps']
    wps = json.loads((inbox / 'wps.json').read_text(encoding='utf-8'))
    assert wps == {'cookie': 'wps_sid=abc; other=1'}          # cookie 平台归 cookie 字段
    qoder = json.loads((inbox / 'qoder.json').read_text(encoding='utf-8'))
    assert qoder == {'token': 'dt-token-1'}
    ms = json.loads((inbox / 'modelscope.json').read_text(encoding='utf-8'))
    assert ms['cookie'].startswith('m_session_id')


def test_scan_no_home_files(tmp_path):
    inbox = tmp_path / 'inbox'
    assert scan_local_accounts(inbox, home=tmp_path / 'nobody') == []
    assert not (inbox / 'wps.json').exists()


def test_scan_result_is_importable(tmp_path):
    from app.credentials import CredentialStore
    inbox = tmp_path / 'data' / 'inbox'
    scan_local_accounts(inbox, home=_fake_home(tmp_path))
    store = CredentialStore(tmp_path / 'data', {'wps', 'qoder', 'modelscope'})
    imported = dict(store.import_inbox())
    assert sorted(imported) == ['modelscope', 'qoder', 'wps']
