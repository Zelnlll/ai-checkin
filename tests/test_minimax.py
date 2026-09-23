import hashlib

import pytest

from app.http import OpError
import app.platforms.minimax as m
from app.platforms.minimax import MinimaxAdapter, minimax_headers

SIGN_SALT = 'I*7Cf%WZ#S&%1RlZJ&C2'   # 官方客户端硬编码常量（agent_ext.rs L43-45）
YY_SALT = 'ooui'


def test_x_signature_golden_get_empty_body():
    h = minimax_headers('tok', '/x?a=1', '', ts='1700000000', ms='1700000000123')
    assert h['x-signature'] == hashlib.md5(
        ('1700000000' + SIGN_SALT).encode()).hexdigest()


def test_x_signature_golden_post_with_body():
    body = '{"k":1}'
    h = minimax_headers('tok', '/x', body, ts='1700000000', ms='1700000000123')
    assert h['x-signature'] == hashlib.md5(
        ('1700000000' + SIGN_SALT + body).encode()).hexdigest()


def test_yy_golden_get_signs_empty_body_as_braces():
    from urllib.parse import quote
    path = '/minimax-cloud/api/v1/signin/status?timezone_id=Asia/Shanghai'
    h = minimax_headers('tok', path, '', ts='1700000000', ms='1700000000123')
    expected = hashlib.md5((
        quote(path, safe="-_.!~*'()") + '_' + '{}'
        + hashlib.md5(b'1700000000123').hexdigest() + YY_SALT
    ).encode()).hexdigest()
    assert h['yy'] == expected


def test_headers_carry_token_dual_and_ua():
    h = minimax_headers('jwt-token', '/x', '', ts='1', ms='2')
    assert h['token'] == 'jwt-token'
    assert h['Authorization'] == 'Bearer jwt-token'
    assert h['User-Agent'] == 'MiniMaxCode'


@pytest.fixture
def mm(local_server, monkeypatch):
    monkeypatch.setattr(m, 'MINIMAX_BASE', local_server.base)
    monkeypatch.setattr(m, 'MINIMAX_BASE_ALT', local_server.base)
    return MinimaxAdapter()


def _status_body(today_status):
    return {"base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"days": [
                {"date": "09-21", "is_today": False, "status": 3},
                {"date": "09-22", "is_today": True, "status": today_status,
                 "points": 400}]}}


def test_claimable_status_2_claims_and_returns_ok(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body=_status_body(2))
    local_server.route('POST', '/minimax-cloud/api/v1/signin/claim',
                       body={"base_resp": {"status_code": 0},
                             "data": {"claim_result": 1, "points": 400}})
    r = mm.checkin({'token': 'jwt'})
    assert r.state == 'ok' and '400' in r.reward


def test_status_3_is_already_without_claim(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body=_status_body(3))
    r = mm.checkin({'token': 'jwt'})
    assert r.state == 'already' and '400' in r.message
    assert r.reward == '+400 积分'      # 面板"今日已得"读 reward
    assert [x for x in local_server.received if x['method'] == 'POST'] == []


def test_claim_result_2_maps_already(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body=_status_body(2))
    local_server.route('POST', '/minimax-cloud/api/v1/signin/claim',
                       body={"base_resp": {"status_code": 0},
                             "data": {"claim_result": 2}})
    r = mm.checkin({'token': 'jwt'})
    assert r.state == 'already'


def test_auth_status_code_raises_auth(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body={"base_resp": {"status_code": 1022100011,
                                           "status_msg": "token invalid"}})
    with pytest.raises(OpError) as exc:
        mm.checkin({'token': 'jwt'})
    assert exc.value.kind == 'auth'


def test_business_error_returns_error_state(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body={"base_resp": {"status_code": 999, "status_msg": "bad"}})
    r = mm.checkin({'token': 'jwt'})
    assert r.state == 'error' and '999' in r.message


def test_busy_message_maps_busy(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/signin/status',
                       body=_status_body(2))
    local_server.route('POST', '/minimax-cloud/api/v1/signin/claim',
                       body={"base_resp": {"status_code": 500,
                                           "status_msg": "服务器繁忙，请稍后重试"}})
    r = mm.checkin({'token': 'jwt'})
    assert r.state == 'busy'


def test_transport_failure_falls_back_to_alt_domain(monkeypatch):
    monkeypatch.setattr(m, 'MINIMAX_BASE', 'http://127.0.0.1:1')
    import tests.conftest as c
    srv = c.LocalServer().start()
    try:
        srv.route('GET', '/minimax-cloud/api/v1/signin/status', body=_status_body(3))
        monkeypatch.setattr(m, 'MINIMAX_BASE_ALT', srv.base)
        r = MinimaxAdapter().checkin({'token': 'jwt'})
        assert r.state == 'already'
    finally:
        srv.stop()


def test_missing_token_raises_auth():
    with pytest.raises(OpError) as exc:
        MinimaxAdapter().checkin({'token': ''})
    assert exc.value.kind == 'auth'


def test_credits_sums_valid_packages(mm, local_server):
    # 真实 web 响应：无 data 包裹，details/total_count 直接顶层（2026-09-23 实测）
    local_server.route('GET', '/minimax-cloud/api/v1/credit/details',
                       body={"base_resp": {"status_code": 0}, "details": [
                           {"credit_type": 2, "granted_amount": "400.00",
                            "remaining_amount": "350.00",
                            "expire_at_ms": 4102415999000},
                           {"credit_type": 1, "remaining_amount": "50.00",
                            "expire_at_ms": 946684800000},
                       ], "total_count": 1})
    assert mm.credits({'token': 'jwt'}) == '350'


def test_credits_legacy_fields_compat(mm, local_server):
    local_server.route('GET', '/minimax-cloud/api/v1/credit/details',
                       body={"base_resp": {"status_code": 0}, "data": {"details": [
                           {"amount": 100, "remain": 80,
                            "expire_time": "2099-01-01T00:00:00+08:00"},
                           {"amount": 50, "remain": 50,
                            "expire_time": "2000-01-01T00:00:00+08:00"},
                       ]}})
    assert mm.credits({'token': 'jwt'}) == '80'


def test_token_status_works_with_jwt():
    from tests.conftest import make_jwt
    import time
    tok = make_jwt({'exp': int(time.time()) + 864000})
    st = MinimaxAdapter().token_status({'token': tok})
    assert st['known'] is True and st['expired'] is False
