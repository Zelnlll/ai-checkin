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
    p = minimax_web.build_web_path('/x', FAKE_JWT, now_ms=1790125591000)
    assert p.startswith('/x?')
    assert 'token=' + FAKE_JWT[:20] in p
    assert 'user_id=U42' in p
    assert 'client=web' in p
    assert 'timezone_offset=28800' in p
    assert 'unix=1790125591000' in p
    # 同输入必须逐字节稳定（yy 签名与实发 URL 强一致）
    assert p == minimax_web.build_web_path('/x', FAKE_JWT, now_ms=1790125591000)


def test_web_request_success_with_sig_headers(monkeypatch):
    calls = []

    def fake_fetch(state, origin, path_q, headers, body):
        calls.append((state, origin, path_q, headers, body))
        return 200, '{"data": {"days": []}}'
    monkeypatch.setattr(minimax_web, 'in_page_fetch', fake_fetch)
    payload = minimax_web.web_request('/minimax-cloud/api/v1/signin/status',
                                      None, FAKE_JWT, 'browser/minimax.json')
    assert payload['data'] == {'days': []}
    hdrs = calls[0][3]
    assert hdrs['token'] == FAKE_JWT
    assert 'x-signature' in hdrs and 'yy' in hdrs and 'x-timestamp' in hdrs
    assert 'Cookie' not in hdrs and 'User-Agent' not in hdrs


def test_web_request_post_body(monkeypatch):
    seen = {}

    def fake_fetch(state, origin, path_q, headers, body):
        seen['body'] = body
        seen['sig'] = headers['x-signature']
        return 200, '{"data": {}}'
    monkeypatch.setattr(minimax_web, 'in_page_fetch', fake_fetch)
    minimax_web.web_request('/m/claim', {}, FAKE_JWT, 'browser/minimax.json',
                            now_ms=1790125591000)
    assert seen['body'] == '{}'
    from app.platforms.minimax import minimax_headers
    expect = minimax_headers(FAKE_JWT,
                             minimax_web.build_web_path('/m/claim', FAKE_JWT,
                                                         now_ms=1790125591000),
                             '{}', ts='1790125591', ms='1790125591000')
    assert seen['sig'] == expect['x-signature']


def test_web_request_401_is_auth_error(monkeypatch):
    monkeypatch.setattr(minimax_web, 'in_page_fetch',
                        lambda *a, **k: (401, ''))
    with pytest.raises(OpError) as e:
        minimax_web.web_request('/x', None, FAKE_JWT, 'browser/minimax.json')
    assert e.value.kind == 'auth'


def test_adapter_routes_web_session(monkeypatch):
    from app.platforms.minimax import MinimaxAdapter
    hits = []

    def fake_web(path_q, body, token, state):
        hits.append((path_q, body, state))
        return {'data': {'days': [{'is_today': True, 'status': 3,
                                   'points': 400}]}}
    monkeypatch.setattr('app.minimax_web.web_request', fake_web)
    res = MinimaxAdapter().checkin({'token': FAKE_JWT,
                                    'browser_state': 'browser/minimax.json'})
    assert res.state == 'already' and '400' in res.message
    assert hits[0][0].startswith('/minimax-cloud/api/v1/signin/status?')
    assert hits[0][2] == 'browser/minimax.json'
