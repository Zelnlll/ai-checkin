import pytest

from app.http import OpError
import app.platforms.baidu_dazi as m
from app.platforms.baidu_dazi import BaiduDaziAdapter, derive_csrf


def test_csrf_derived_from_bce_user_info():
    cookie = r'a=1; bce-user-info=\"u-12345-abc\"; b=2'
    assert derive_csrf(cookie) == 'u-12345-abc'


def test_csrf_empty_when_cookie_missing_field():
    assert derive_csrf('a=1') == ''


@pytest.fixture
def dazi(local_server, monkeypatch):
    monkeypatch.setattr(m, 'DUMATE_BASE', local_server.base)
    return BaiduDaziAdapter()


COOKIE = r'bce-user-info=\"u-12345-abc\"; other=x'


def test_claim_success_returns_ok_plus_500(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 0, "message": "success",
                             "result": {"hasIssued": False, "signInDays": ["09-20", "09-21"]}})
    local_server.route('POST', '/api/dumate/points/loginBonus',
                       body={"code": 0, "message": "success", "result": True})
    r = dazi.checkin({'cookie': COOKIE})
    assert r.state == 'ok' and '500' in r.reward


def test_already_issued_skips_claim_request(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 0, "result": {"hasIssued": True,
                                                   "signInDays": ["a"] * 3}})
    r = dazi.checkin({'cookie': COOKIE})
    assert r.state == 'already' and '3' in r.message
    posted = [x for x in local_server.received if x['method'] == 'POST']
    assert posted == []


def test_claim_returns_false_maps_already(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 0, "result": {"hasIssued": False, "signInDays": []}})
    local_server.route('POST', '/api/dumate/points/loginBonus',
                       body={"code": 0, "result": False})
    r = dazi.checkin({'cookie': COOKIE})
    assert r.state == 'already'


def test_sends_derived_csrftoken_header(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 0, "result": {"hasIssued": True, "signInDays": []}})
    dazi.checkin({'cookie': COOKIE})
    headers = {k.lower(): v for k, v in local_server.received[-1]['headers'].items()}
    assert headers['csrftoken'] == 'u-12345-abc'


def test_login_page_html_raises_auth_error(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       raw='<html>登录</html>', content_type='text/html')
    with pytest.raises(OpError) as exc:
        dazi.checkin({'cookie': 'bad'})
    assert exc.value.kind == 'auth' and 'Cookie' in str(exc.value)


def test_envelope_code_302_raises_auth_error(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 302, "message": "need login"})
    with pytest.raises(OpError) as exc:
        dazi.checkin({'cookie': 'bad'})
    assert exc.value.kind == 'auth'


def test_business_code_is_error_not_auth(dazi, local_server):
    local_server.route('GET', '/api/dumate/points/loginBonusInfo',
                       body={"code": 50001, "message": "internal quota error"})
    r = dazi.checkin({'cookie': COOKIE})
    assert r.state == 'error' and '50001' in r.message
