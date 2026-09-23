from app.browser_login import _extract_state, _login_done


class FakeCtx:
    def __init__(self, cookies):
        self._c = cookies

    def cookies(self):
        return self._c


class FakePage:
    def __init__(self, token):
        self._t = token

    def evaluate(self, script):
        return self._t


def test_extract_state_finds_jwt_token():
    assert _extract_state(FakeCtx([]), FakePage('eyJabc')) == {'token': 'eyJabc'}


def test_extract_state_cookie_only():
    ctx = FakeCtx([{'name': 'a', 'value': '1'}])
    assert _extract_state(ctx, FakePage(None)) == {'cookie': 'a=1'}


def test_extract_state_empty_is_none():
    assert _extract_state(FakeCtx([]), FakePage(None)) is None


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
