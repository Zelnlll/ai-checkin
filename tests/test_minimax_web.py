import base64
import json

import pytest

from app import minimax_web
from app.http import OpError

FAKE_JWT = '.'.join([
    base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip('='),
    base64.urlsafe_b64encode(
        json.dumps({'exp': 9e9, 'user': {'id': 'U42', 'name': 'x'}}).encode()
    ).decode().rstrip('='),
    'sig',
])


def test_build_web_path_has_auth_params():
    p = minimax_web.build_web_path('/x', FAKE_JWT, 'U9', now_ms=1790125591000)
    assert p.startswith('/x?')
    assert 'token=' + FAKE_JWT[:20] in p
    assert 'user_id=U9' in p
    assert 'timezone_id=Asia%2FShanghai' in p
    assert 'op_ticket=undefined' in p
    assert p.count('unix=1790125591000') == 2
    assert p.split('?')[1].count('timezone_id') == 1
    # 同输入必须逐字节稳定（yy 签名与实发 URL 强一致）
    assert p == minimax_web.build_web_path('/x', FAKE_JWT, 'U9', now_ms=1790125591000)


def test_build_web_path_strips_legacy_query():
    p = minimax_web.build_web_path('/x?timezone_id=Asia/Shanghai', FAKE_JWT, 'U9',
                                   now_ms=1)
    assert p.startswith('/x?')
    assert p.count('timezone_id') == 1


def test_web_request_success(monkeypatch):
    calls = []

    def fake_http(method, url, headers, body=None, timeout=25):
        calls.append((method, url, headers, body))
        return {'data': {'days': []}}
    monkeypatch.setattr(minimax_web, 'http_json', fake_http)
    payload = minimax_web.web_request('/minimax-cloud/api/v1/signin/status',
                                      None, FAKE_JWT, 'U9')
    assert payload['data'] == {'days': []}
    m, url, hdrs, body = calls[0]
    assert m == 'GET' and body is None
    assert 'user_id=U9' in url
    assert url.startswith('https://agent.minimaxi.com/minimax-cloud')
    assert hdrs['token'] == FAKE_JWT
    assert hdrs['x-signature'] and hdrs['yy'] and hdrs['x-timestamp']
    assert hdrs['Referer'].endswith('agent.minimaxi.com/')
    assert 'Cookie' not in hdrs


def test_web_request_missing_user_id_is_auth(monkeypatch):
    with pytest.raises(OpError) as e:
        minimax_web.web_request('/x', None, FAKE_JWT, '')
    assert e.value.kind == 'auth'


def test_web_request_post_claim_signature(monkeypatch):
    seen = {}

    def fake_http(method, url, headers, body=None, timeout=25):
        seen['method'] = method
        seen['sig'] = headers['x-signature']
        return {'data': {}}
    monkeypatch.setattr(minimax_web, 'http_json', fake_http)
    minimax_web.web_request('/m/claim', {}, FAKE_JWT, 'U9',
                            now_ms=1790125591000)
    assert seen['method'] == 'POST'
    from app.platforms.minimax import minimax_headers
    expect = minimax_headers(
        FAKE_JWT,
        minimax_web.build_web_path('/m/claim', FAKE_JWT, 'U9',
                                   now_ms=1790125591000),
        '{}', ts='1790125591', ms='1790125591000')
    assert seen['sig'] == expect['x-signature']


def test_web_request_401_mapped_to_auth(monkeypatch):
    def fake_http(*a, **k):
        raise OpError('HTTP 401：HTTP 401', kind='http')
    monkeypatch.setattr(minimax_web, 'http_json', fake_http)
    with pytest.raises(OpError) as e:
        minimax_web.web_request('/x', None, FAKE_JWT, 'U9')
    assert e.value.kind == 'auth'


def test_adapter_routes_web_session(monkeypatch):
    from app.platforms.minimax import MinimaxAdapter
    hits = []

    def fake_web(path_q, body, token, user_id, now_ms=None):
        hits.append((path_q, body))
        return {'data': {'days': [{'is_today': True, 'status': 3,
                                   'points': 400}]}}
    monkeypatch.setattr('app.minimax_web.web_request', fake_web)
    res = MinimaxAdapter().checkin({'token': FAKE_JWT, 'web_session': True,
                                    'user_id': 'U9'})
    assert res.state == 'already' and '400' in res.message
    assert hits[0][0].startswith('/minimax-cloud/api/v1/signin/status?')
