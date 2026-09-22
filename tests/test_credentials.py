import json

from app.credentials import CredentialStore

KNOWN = {'wps', 'minimax'}


def make_store(tmp_path):
    (tmp_path / 'inbox').mkdir()
    return CredentialStore(tmp_path, KNOWN)


def test_inbox_import_writes_credential_and_renames_source(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "kso_sid=abc"}', encoding='utf-8')
    assert store.import_inbox() == [('wps', 'wps.json')]
    assert store.load('wps')['cookie'] == 'kso_sid=abc'
    assert not (tmp_path / 'inbox' / 'wps.json').exists()
    assert (tmp_path / 'inbox' / 'wps.json.imported').exists()


def test_corrupt_inbox_file_skipped_without_touching_existing(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'good'})
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cooki', encoding='utf-8')
    assert store.import_inbox() == []
    assert store.load('wps')['cookie'] == 'good'


def test_unknown_platform_inbox_file_ignored(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wechat.json').write_text('{"token": "x"}', encoding='utf-8')
    assert store.import_inbox() == []
    assert store.load('wechat') is None


def test_inbox_file_missing_credential_field_rejected(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wps.json').write_text('{"note": "没有凭证字段"}', encoding='utf-8')
    assert store.import_inbox() == []
    assert store.load('wps') is None


def test_save_adds_saved_at_timestamp(tmp_path):
    store = make_store(tmp_path)
    store.save('minimax', {'token': 'jwt'})
    assert store.load('minimax')['saved_at']


def test_expiry_report_estimates_cookie_age(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'kso_sid=x'})
    (tmp_path / 'credentials' / 'wps.json').write_text(json.dumps(
        {'cookie': 'kso_sid=x', 'saved_at': '2020-01-01T00:00:00'}), encoding='utf-8')

    class BareAdapter:
        credential_kind = 'cookie'

        def token_status(self, creds):
            return {'known': False, 'expired': False, 'expires_at': '', 'days_left': None}

    report = store.expiry_report('wps', store.load('wps'), BareAdapter())
    assert report['likely_expired_soon'] is True
