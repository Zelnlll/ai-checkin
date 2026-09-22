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
    assert status['platforms'][0]['last_done'] == yesterday


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
    assert 'textarea' in html and '网页登录' in html


def test_api_scan_endpoint(tmp_path, monkeypatch):
    import app.webapp as webapp
    monkeypatch.setattr(webapp, 'scan_local_accounts',
                        lambda inbox, home=None: ['wps', 'qoder'])
    cfg = Config((10, 5), 3, '', tmp_path)
    httpd, base = _start_server(cfg)
    try:
        resp = _post(f'{base}/api/scan', {})
        assert resp['ok'] is True and resp['platforms'] == ['wps', 'qoder']
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
