import pytest

from app.http import OpError, http_json, jwt_exp_s, jwt_sub
from tests.conftest import make_jwt


def test_returns_parsed_json_on_200(local_server):
    local_server.route('GET', '/ok', body={"a": 1})
    assert http_json('GET', f'{local_server.base}/ok', {}) == {"a": 1}


def test_post_sends_json_body_and_headers(local_server):
    local_server.route('POST', '/echo', body={"ok": True})
    http_json('POST', f'{local_server.base}/echo', {'X-Tag': 't'}, body={"k": "v"})
    last = local_server.received[-1]
    assert last['headers']['X-Tag'] == 't'
    assert b'"k"' in last['body']


def test_401_raises_auth_error(local_server):
    local_server.route('GET', '/deny', body={"message": "unauthorized"}, status=401)
    with pytest.raises(OpError) as exc:
        http_json('GET', f'{local_server.base}/deny', {})
    assert exc.value.kind == 'auth'
    assert exc.value.http_status == 401
    assert 'unauthorized' in str(exc.value)


def test_500_raises_http_error(local_server):
    local_server.route('GET', '/boom', body={"message": "internal"}, status=500)
    with pytest.raises(OpError) as exc:
        http_json('GET', f'{local_server.base}/boom', {})
    assert exc.value.kind == 'http'


def test_html_login_page_raises_parse_error(local_server):
    local_server.route('GET', '/html', raw='<html>login</html>', content_type='text/html')
    with pytest.raises(OpError) as exc:
        http_json('GET', f'{local_server.base}/html', {})
    assert exc.value.kind == 'parse'


def test_network_error_kind_is_network():
    with pytest.raises(OpError) as exc:
        http_json('GET', 'http://127.0.0.1:1/x', {}, timeout=2)
    assert exc.value.kind == 'network'


def test_jwt_exp_s_extracts_expiry():
    assert jwt_exp_s(make_jwt({'exp': 1700000000})) == 1700000000


def test_jwt_exp_s_zero_on_garbage():
    assert jwt_exp_s('not-a-jwt') == 0


def test_jwt_sub_extracts_subject():
    assert jwt_sub(make_jwt({'sub': 'user-1'})) == 'user-1'
