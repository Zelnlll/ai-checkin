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


def test_reimport_same_platform_twice(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "first"}', encoding='utf-8')
    assert store.import_inbox() == [('wps', 'wps.json')]
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "second"}', encoding='utf-8')
    assert store.import_inbox() == [('wps', 'wps.json')]   # 旧 .imported 存在不许炸
    assert store.load('wps')['cookie'] == 'second'


def test_partial_import_merges_with_existing(tmp_path):
    (tmp_path / 'inbox').mkdir()
    store = CredentialStore(tmp_path, {'wps', 'minimax', 'modelscope'})
    store.save('modelscope', {'cookie': 'm_session_id=a', 'token': 'ms-keep'})
    (tmp_path / 'inbox' / 'modelscope.json').write_text(
        '{"cookie": "m_session_id=b"}', encoding='utf-8')
    store.import_inbox()
    creds = store.load('modelscope')
    assert creds['cookie'] == 'm_session_id=b'   # 新字段覆盖
    assert creds['token'] == 'ms-keep'           # 已有字段保留


def test_clear_removes_credential_and_inbox(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'x'})
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "y"}', encoding='utf-8')
    (tmp_path / 'inbox' / 'wps.json.imported').write_text('{}', encoding='utf-8')
    result = store.clear('wps')
    assert result['cleared'] is True
    assert store.load('wps') is None
    assert not (tmp_path / 'inbox' / 'wps.json').exists()
    assert not (tmp_path / 'inbox' / 'wps.json.imported').exists()


def test_saved_at_refreshes_only_on_change(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'v1'})
    (tmp_path / 'credentials' / 'wps.json').write_text(
        json.dumps({'cookie': 'v1', 'saved_at': '2020-01-01T00:00:00'}), encoding='utf-8')
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "v1"}', encoding='utf-8')
    store.import_inbox()
    assert store.load('wps')['saved_at'] == '2020-01-01T00:00:00'   # 值没变不刷新
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "v2"}', encoding='utf-8')
    store.import_inbox()
    assert store.load('wps')['saved_at'] != '2020-01-01T00:00:00'   # 变了刷新，临期提醒可消除


# ---------- 多账号 ----------

def test_legacy_flat_file_loads_as_single_main(tmp_path):
    (tmp_path / 'credentials').mkdir()
    (tmp_path / 'credentials' / 'wps.json').write_text(
        json.dumps({'cookie': 'old'}), encoding='utf-8')
    store = CredentialStore(tmp_path, KNOWN)
    assert store.load('wps')['cookie'] == 'old'
    accts = store.load_all('wps')
    assert len(accts) == 1 and accts[0]['id'] == 'main'


def test_load_all_empty_returns_empty_list(tmp_path):
    store = make_store(tmp_path)
    assert store.load_all('wps') == []
    assert store.load('wps') is None


def test_save_keeps_single_main_account_format(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'x'})
    raw = json.loads((tmp_path / 'credentials' / 'wps.json').read_text(encoding='utf-8'))
    assert raw['accounts'][0]['id'] == 'main'
    assert store.load('wps')['cookie'] == 'x'


def test_upsert_matching_credential_merges_in_place(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'v1'})
    store.upsert('wps', {'cookie': 'v1', 'csrf': 'c9'})
    accts = store.load_all('wps')
    assert len(accts) == 1 and accts[0]['csrf'] == 'c9'
    store.upsert('wps', {'cookie': 'other'})       # 不匹配则视为新账号
    assert len(store.load_all('wps')) == 2


def test_upsert_explicit_id_targets_account(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'a'})
    store.upsert('wps', {'cookie': 'b', 'label': '二号'})
    accts = store.load_all('wps')
    assert len(accts) == 2 and accts[1]['label'] == '二号'
    store.upsert('wps', {'cookie': 'b2'}, acct_id=accts[1]['id'])
    accts = store.load_all('wps')
    assert len(accts) == 2 and accts[1]['cookie'] == 'b2'
    assert accts[1]['id'] and accts[1]['id'] != 'main'


def test_upsert_second_credential_appends(tmp_path):
    store = make_store(tmp_path)
    store.save('minimax', {'token': 't1'})
    store.upsert('minimax', {'token': 't2'})
    assert [a['token'] for a in store.load_all('minimax')] == ['t1', 't2']


def test_inbox_import_appends_second_account_when_multiple(tmp_path):
    store = make_store(tmp_path)
    store.save('minimax', {'token': 't1'})
    store.upsert('minimax', {'token': 't2'})
    (tmp_path / 'inbox' / 'minimax.json').write_text('{"token": "t3"}', encoding='utf-8')
    store.import_inbox()
    assert [a['token'] for a in store.load_all('minimax')] == ['t1', 't2', 't3']


def test_inbox_import_rotates_single_account(tmp_path):
    store = make_store(tmp_path)
    store.save('minimax', {'token': 't1'})
    (tmp_path / 'inbox' / 'minimax.json').write_text('{"token": '
                                                     '"t1-rotated"}', encoding='utf-8')
    store.import_inbox()
    accts = store.load_all('minimax')
    assert len(accts) == 1 and accts[0]['token'] == 't1-rotated'


def test_remove_single_account_keeps_others(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'a'})
    store.upsert('wps', {'cookie': 'b'})
    b = store.load_all('wps')[1]
    store.remove('wps', acct_id=b['id'])
    assert [a['cookie'] for a in store.load_all('wps')] == ['a']


def test_remove_without_id_clears_all(tmp_path):
    store = make_store(tmp_path)
    store.save('wps', {'cookie': 'a'})
    store.remove('wps')
    assert store.load('wps') is None


def test_upsert_sanitizes_label_and_illegal_id(tmp_path):
    store = make_store(tmp_path)
    store.upsert('wps', {'cookie': 'a', 'label': '主"><svg onload=x>'})
    store.upsert('wps', {'cookie': 'b'}, acct_id='"><script>x</script>')
    accts = store.load_all('wps')
    assert '<' not in accts[0]['label'] and '"' not in accts[0]['label']
    assert all(a['id'].isalnum() or set(a['id']) <= set('_-')
               for a in accts)


def test_first_inbox_import_gets_main_id(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "c"}', encoding='utf-8')
    store.import_inbox()
    assert store.load_all('wps')[0]['id'] == 'main'


def test_inbox_replace_twice_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    (tmp_path / 'inbox' / 'wps.json').write_text('{"cookie": "c"}', encoding='utf-8')
    store.import_inbox()
    # 模拟并发：文件已被改名，再跑一轮不许抛
    store.import_inbox()


def test_concurrent_upserts_all_survive(tmp_path):
    import threading
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'cookie': 'base'})
    threads = [threading.Thread(
        target=store.upsert, args=('wps', {'cookie': f'c{i}'}))
        for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cookies = {a['cookie'] for a in store.load_all('wps')}
    assert len(cookies) == 21        # 20 个并发号一个不丢
