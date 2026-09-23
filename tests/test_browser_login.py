from app.browser_login import _capture_request, _extract_state, _login_done


class FakeReq:
    def __init__(self, url, headers):
        self.url = url
        self.headers = headers


MM_SPEC = {'url': 'x', 'local_storage': 'token', 'web_session': True,
           'capture': {'url': 'minimax-cloud', 'header': 'token'}}
LA_SPEC = {'url': 'x', 'local_storage': 'token',
           'capture': {'url': 'link-ai.tech/api', 'header': 'authorization',
                       'strip': 'Bearer '}}


def test_capture_minimax_token_and_user_id():
    captured = {}
    req = FakeReq('https://agent.minimaxi.com/minimax-cloud/api/v1/x?user_id=U9',
                  {'token': 'JWT-MM'})
    _capture_request(MM_SPEC, captured, req)
    assert captured['token'] == 'JWT-MM' and captured['user_id'] == 'U9'


def test_capture_linkai_bearer_authorization():
    captured = {}
    req = FakeReq('https://link-ai.tech/api/chat/web/app/user/get/balance',
                  {'authorization': 'Bearer JWT-LA'})
    _capture_request(LA_SPEC, captured, req)
    assert captured['token'] == 'JWT-LA'


def test_capture_ignores_other_urls_and_first_wins():
    captured = {}
    _capture_request(LA_SPEC, captured,
                     FakeReq('https://link-ai.tech/console/account',
                             {'authorization': 'Bearer X'}))
    assert captured == {}
    _capture_request(LA_SPEC, captured,
                     FakeReq('https://link-ai.tech/api/a', {'authorization': 'Bearer T1'}))
    _capture_request(LA_SPEC, captured,
                     FakeReq('https://link-ai.tech/api/b', {'authorization': 'Bearer T2'}))
    assert captured['token'] == 'T1'


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
