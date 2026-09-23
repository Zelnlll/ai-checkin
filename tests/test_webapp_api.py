import json
import urllib.request
from datetime import date, timedelta

from app.config import Config
from app.credentials import CredentialStore
from app.platforms import ADAPTERS
from app.platforms.base import Adapter, CheckinResult
from app.state import DailyState
from app.webapp import collect_status, render_settings, serve_app


class Stub(Adapter):
    platform = 'stub'
    title = 'Stub'
    credential_kind = 'token'

    def checkin(self, creds):
        return CheckinResult('ok', 'stub 成功', '+1')


def _start_server(cfg):
    httpd = serve_app(cfg, port=0)
    import threading
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{httpd.server_address[1]}'


def _post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode('utf-8'))


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read().decode('utf-8')


def test_status_includes_last_done_date(tmp_path):
    state = DailyState(tmp_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    state.mark('wps', CheckinResult('ok', 'x'), yesterday)
    store = CredentialStore(tmp_path, {'wps'})
    status = collect_status(None, store, state, ['wps'])
    last_done = status['platforms'][0]['last_done']
    # 日期 + 当次执行时刻合并显示
    assert last_done.startswith(f'{yesterday} ')
    assert len(last_done.split(' ')[1]) == 8  # HH:MM:SS


def test_last_done_shows_today_time(tmp_path):
    state = DailyState(tmp_path)
    today = date.today().isoformat()
    state.mark('wps', CheckinResult('ok', 'x'), today)
    store = CredentialStore(tmp_path, {'wps'})
    status = collect_status(None, store, state, ['wps'])
    assert status['platforms'][0]['last_done'].startswith('今天 ')


def test_post_credentials_saves_and_imports(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        resp = _post(f'{base}/api/credentials/wps', {'cookie': 'wps_sid=new'})
        assert resp['ok'] is True
        store = CredentialStore(tmp_path, {'wps'})
        assert store.load('wps')['cookie'] == 'wps_sid=new'
    finally:
        httpd.shutdown(); httpd.server_close()


def test_post_credentials_rejects_empty(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        resp = _post(f'{base}/api/credentials/wps', {'cookie': ''})
        assert resp['ok'] is False and 'cookie' in resp['message']
    finally:
        httpd.shutdown(); httpd.server_close()


def test_post_checkin_runs_platform(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'stub'})
    store.save('stub', {'token': 't'})
    ADAPTERS['stub'] = Stub()
    httpd, base = _start_server(cfg)
    try:
        resp = _post(f'{base}/api/checkin/stub', {})
        assert resp['ok'] is True and resp['state'] == 'ok'
        assert DailyState(tmp_path).done_today('stub')
    finally:
        del ADAPTERS['stub']
        httpd.shutdown(); httpd.server_close()


def test_settings_page_lists_platforms():
    html = render_settings({'today': '', 'platforms': [
        {'platform': 'wps', 'title': 'WPS 灵犀', 'credential': '已导入'},
    ]})
    assert '设置' in html and 'WPS 灵犀' in html
    assert 'textarea' in html and '添加账号' in html
    assert '网页登录' not in html and '扫描本机' not in html


def test_api_scan_endpoint_removed(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        req = urllib.request.Request(
            f'{base}/api/scan', data=b'{}',
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, '应 404'
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown(); httpd.server_close()


def test_dashboard_shows_keepalive_row(tmp_path):
    from app.webapp import render_html
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'cookie': 'wps_sid=1'})
    state = DailyState(tmp_path)
    state.touch_keepalive('wps', date.today().isoformat())
    html = render_html(collect_status(cfg, store, state, ['wps']))
    assert '保活' in html


def test_settings_per_field_inputs():
    from app.webapp import render_settings
    status = {'today': '', 'platforms': [
        {'platform': 'modelscope', 'title': '魔搭', 'credential': '已导入'},
        {'platform': 'qoder', 'title': 'Qoder', 'credential': '未导入凭证'},
        {'platform': 'wps', 'title': 'WPS 灵犀', 'credential': '未导入凭证'},
    ]}
    html = render_settings(status)
    assert 'cred-modelscope-cookie' in html      # 魔搭两个独立输入口
    assert 'cred-modelscope-token' in html
    assert 'SDK 令牌' in html
    assert 'cred-qoder-token' in html            # Qoder 只有令牌框
    assert 'cred-qoder-cookie' not in html
    assert 'cred-wps-cookie' in html             # 灵犀只有 Cookie 框
    assert 'cred-wps-token' not in html


def test_dashboard_survives_minimax_jwt_credential(tmp_path):
    """C1 回归：minimax 存 JWT 后面板整页不许炸。"""
    from tests.conftest import make_jwt
    import time
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'minimax'})
    store.save('minimax', {'token': make_jwt({'exp': int(time.time()) + 864000})})
    httpd, base = _start_server(cfg)
    try:
        import urllib.request
        with urllib.request.urlopen(base + '/', timeout=10) as r:
            assert r.status == 200 and 'MiniMax' in r.read().decode('utf-8')
    finally:
        httpd.shutdown(); httpd.server_close()


def test_api_login_endpoint_removed(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        req = urllib.request.Request(
            f'{base}/api/login/wps', data=b'{}',
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, '应 404'
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown(); httpd.server_close()


def test_handler_exception_returns_json_500(tmp_path, monkeypatch):
    """I1 回归：后端炸了要返回结构化错误，不能掐连接。"""
    import app.webapp as webapp

    def boom(*a, **k):
        raise RuntimeError('磁盘炸了')
    monkeypatch.setattr(webapp, 'collect_status', boom)
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        import urllib.request
        try:
            urllib.request.urlopen(base + '/', timeout=10)
            raised = None
        except urllib.error.HTTPError as e:
            raised = e
        assert raised is not None and raised.code == 500
        assert b'ok' in raised.read()
    finally:
        httpd.shutdown(); httpd.server_close()


def test_api_detail_rows(tmp_path, monkeypatch):
    from app.platforms import get_adapter
    monkeypatch.setattr(get_adapter('wps'), 'breakdown', lambda creds: [
        {'tag': '通用', 'name': '每月登录', 'amount': '500', 'expire': '7天后过期'}])
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'cookie': 'wps_sid=x'})
    httpd, base = _start_server(cfg)
    try:
        resp = json.loads(_get(f'{base}/api/detail/wps'))
        assert resp['ok'] is True
        assert resp['rows'][0]['name'] == '每月登录'
        assert resp['title'] == 'WPS 灵犀'
    finally:
        httpd.shutdown()


def test_api_detail_no_breakdown_note(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'cookie': 'wps_sid=x'})
    httpd, base = _start_server(cfg)
    try:
        resp = json.loads(_get(f'{base}/api/detail/wps'))
        assert resp['ok'] is True and resp['rows'] == []
        assert '不提供' in resp['note']
    finally:
        httpd.shutdown()


def test_api_detail_missing_creds(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        resp = json.loads(_get(f'{base}/api/detail/wps'))
        assert resp['ok'] is False and '未导入' in resp['note']
    finally:
        httpd.shutdown()


def test_api_detail_unknown_platform(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        req = urllib.request.Request(f'{base}/api/detail/nope')
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, '应 404'
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()


# ---------- 多账号 ----------

def test_api_detail_groups_accounts(tmp_path, monkeypatch):
    from app.platforms import get_adapter
    def fake_bd(creds):
        return [{'tag': '资源包', 'name': '包', 'amount': creds['token'] + '0',
                 'expire': '7天后过期（10-01）'}]
    monkeypatch.setattr(get_adapter('wps'), 'breakdown', fake_bd)
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'token': 'a'})
    store.upsert('wps', {'token': 'b', 'label': '小号'})
    httpd, base = _start_server(cfg)
    try:
        resp = json.loads(_get(f'{base}/api/detail/wps'))
        assert resp['ok'] and len(resp['accounts']) == 2
        assert resp['accounts'][1]['label'] == '小号'
        assert resp['accounts'][0]['rows'][0]['amount'] == 'a0'
    finally:
        httpd.shutdown()


def test_post_credentials_upsert_by_id(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    pre = CredentialStore(tmp_path, {'wps'})
    pre.save('wps', {'cookie': 'a'})
    pre.upsert('wps', {'cookie': 'b', 'label': '二'})
    httpd, base = _start_server(cfg)
    try:
        resp = _post(f'{base}/api/credentials/wps',
                     {'cookie': 'a2', 'id': 'main'})
        assert resp['ok'] is True
        accts = CredentialStore(tmp_path, {'wps'}).load_all('wps')
        assert [a['cookie'] for a in accts] == ['a2', 'b']
    finally:
        httpd.shutdown()


def test_post_credentials_add_new_account(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    CredentialStore(tmp_path, {'wps'}).save('wps', {'cookie': 'a'})
    httpd, base = _start_server(cfg)
    try:
        _post(f'{base}/api/credentials/wps', {'cookie': 'zz', 'label': '新号'})
        accts = CredentialStore(tmp_path, {'wps'}).load_all('wps')
        assert [a['cookie'] for a in accts] == ['a', 'zz']
        assert accts[1]['label'] == '新号'
    finally:
        httpd.shutdown()


def test_post_credentials_clear_one_account(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    pre = CredentialStore(tmp_path, {'wps'})
    pre.save('wps', {'cookie': 'a'})
    b = pre.load_all('wps')
    pre.upsert('wps', {'cookie': 'b'})
    accts = pre.load_all('wps')
    httpd, base = _start_server(cfg)
    try:
        _post(f'{base}/api/credentials/wps', {'clear': True, 'id': accts[1]['id']})
        assert [a['cookie'] for a in
                CredentialStore(tmp_path, {'wps'}).load_all('wps')] == ['a']
    finally:
        httpd.shutdown()


def test_settings_page_lists_accounts(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, {'wps'})
    store.save('wps', {'cookie': 'a'})
    store.upsert('wps', {'cookie': 'b', 'label': '小号'})
    httpd, base = _start_server(cfg)
    try:
        html = _get(f'{base}/settings')
        assert '主账号' in html and '小号' in html and '添加账号' in html
    finally:
        httpd.shutdown()
