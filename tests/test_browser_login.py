from app.browser_login import _capture_request, _extract_state, _login_done


class FakeReq:
    def __init__(self, url, headers):
        self.url = url
        self.headers = headers


MM_SPEC = {'url': 'x', 'local_storage': 'token', 'web_session': True,
           'capture': {'url': 'minimax-cloud', 'header': 'token'}}
BEARER_SPEC = {'url': 'x', 'local_storage': 'token',
               'capture': {'url': 'api.demo.test', 'header': 'authorization',
                           'strip': 'Bearer '}}


def test_capture_minimax_token_and_user_id():
    captured = {}
    req = FakeReq('https://agent.minimaxi.com/minimax-cloud/api/v1/x?user_id=U9',
                  {'token': 'eyJJWT-MM'})
    _capture_request(MM_SPEC, captured, req)
    assert captured['token'] == 'eyJJWT-MM' and captured['user_id'] == 'U9'


def test_capture_bearer_authorization_strips_prefix():
    captured = {}
    req = FakeReq('https://api.demo.test/chat/web/app/user/get/balance',
                  {'authorization': 'Bearer eyJJWT-LA'})
    _capture_request(BEARER_SPEC, captured, req)
    assert captured['token'] == 'eyJJWT-LA'


def test_capture_rejects_non_jwt_and_anon_bearer():
    captured = {}
    for junk in ('Bearer', 'Bearer undefined', 'Bearer 123'):
        _capture_request(BEARER_SPEC, captured,
                         FakeReq('https://api.demo.test/a',
                                 {'authorization': junk}))
    assert captured == {}
    _capture_request(BEARER_SPEC, captured,
                     FakeReq('https://api.demo.test/b',
                             {'authorization': 'Bearer eyJreal'}))
    assert captured['token'] == 'eyJreal'


def test_capture_ignores_other_urls_and_first_wins():
    captured = {}
    _capture_request(BEARER_SPEC, captured,
                     FakeReq('https://console.demo.test',
                             {'authorization': 'Bearer eyJX'}))
    assert captured == {}
    _capture_request(BEARER_SPEC, captured,
                     FakeReq('https://api.demo.test/a', {'authorization': 'Bearer eyJT1'}))
    _capture_request(BEARER_SPEC, captured,
                     FakeReq('https://api.demo.test/b', {'authorization': 'Bearer eyJT2'}))
    assert captured['token'] == 'eyJT1'


class FakeCtx:
    def __init__(self, cookies):
        self._c = cookies

    def cookies(self):
        return self._c


def test_extract_state_uses_header_token():
    assert _extract_state(FakeCtx([]), 'eyJhdr') == {'token': 'eyJhdr'}


def test_extract_state_cookie_only():
    ctx = FakeCtx([{'name': 'a', 'value': '1'}])
    assert _extract_state(ctx) == {'cookie': 'a=1'}


def test_extract_state_empty_is_none():
    assert _extract_state(FakeCtx([]), '') is None


def test_cookie_type_present_and_absent():
    spec = {'url': 'x', 'cookie': 'bce-user-info'}
    assert _login_done(spec, {'cookie': 'a=1; bce-user-info=2'})
    assert not _login_done(spec, {'cookie': 'a=1'})


def test_token_type_no_cookie_key_in_spec():
    # minimax：spec 无 cookie 键，曾因 None in str 抛 TypeError
    spec = {'url': 'x', 'local_storage': 'token'}
    assert _login_done(spec, {'token': 'eyJabc', 'cookie': 'irrelevant=1'})
    assert not _login_done(spec, {'cookie': 'irrelevant=1'})


def test_none_creds_is_false():
    assert not _login_done({'cookie': 'a'}, None)


# ---- 登录票据服务端校验（2026-09-25 半截/过期 Cookie 误导出回归）----

from app.browser_login import PLATFORM_LOGIN, _ready  # noqa: E402

DAZI_SPEC = PLATFORM_LOGIN['dazi']
GOOD = {'cookie': r'BDUSS=b; bce-user-info=\"u-12345-abc\"; bce-sessionid=S1'}


def test_platform_specs_pinned():
    """Cookie 平台必须带 verify；minimax/modelscope 刻意不配（无实证只读端点）。"""
    assert PLATFORM_LOGIN['dazi']['verify']['url'].startswith('https://')
    assert PLATFORM_LOGIN['wps']['verify']['url'].startswith('https://')
    assert 'verify' not in PLATFORM_LOGIN['minimax']
    assert 'verify' not in PLATFORM_LOGIN['modelscope']


def test_ready_rejects_when_server_says_html():
    """storage_state 里 Cookie 全在但服务端打回登录页：判未就绪，绝不静默导出。"""
    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        return '<!DOCTYPE html><html>login'
    assert not _ready(DAZI_SPEC, GOOD, fetch)
    assert calls and calls[0][0] == DAZI_SPEC['verify']['url']


def test_ready_rejects_revoked_json_envelope():
    """真机形态：HTTP 200 + {"code":302,"message":"need login"} 也必须是未就绪。"""
    assert not _ready(DAZI_SPEC, GOOD,
                      lambda u, h: '{"code":302,"message":"need login","result":null}')


def test_ready_accepts_json_and_derives_csrf_and_site_headers():
    seen = {}

    def fetch(url, headers):
        seen.update(headers)
        return '{"code":0,"result":{"hasIssued":true}}'
    assert _ready(DAZI_SPEC, GOOD, fetch)
    assert seen['csrftoken'] == 'u-12345-abc'      # 与 derive_csrf 同规则（去转义引号）
    assert 'bce-sessionid=S1' in seen['Cookie']
    assert seen.get('Origin') and seen.get('Referer')   # 与适配器同发的站点头


def test_ready_marker_absent_skips_network():
    def fetch(url, headers):
        raise AssertionError('marker 未命中不该发校验请求')
    assert not _ready(DAZI_SPEC, {'cookie': 'a=1'}, fetch)


def test_ready_no_verify_spec_passes_like_before():
    """token 型平台（minimax）无 verify：行为与旧版一致。"""
    spec = {'url': 'x', 'local_storage': 'token'}
    assert _ready(spec, {'token': 'eyJabc'}, lambda u, h: '{}')
