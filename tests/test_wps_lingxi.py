import pytest

from app.http import OpError
import app.platforms.wps_lingxi as m
from app.platforms.wps_lingxi import WpsLingxiAdapter


@pytest.fixture
def wps(local_server, monkeypatch):
    monkeypatch.setattr(m, 'WPS_BASE', local_server.base)
    return WpsLingxiAdapter()


def _tasks(status):
    return {"data": {"tasks": [
        {"task_key": "try_group_chat", "status": "incomplete"},
        {"task_key": "daily_check_in", "type": "daily",
         "status": status, "reward_amount": 100},
    ]}}


def test_claim_success_returns_ok_with_reward(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks', body=_tasks('incomplete'))
    local_server.route('POST', '/api/public/v1/tasks/daily_check_in/claim',
                       body={"data": {"task_key": "daily_check_in",
                                      "reward_amount": 100,
                                      "trade_no": "lx_task_1"}})
    r = wps.checkin({'cookie': 'wps_sid=abc'})
    assert r.state == 'ok' and '100' in r.reward


def test_already_claimed_status_maps_already(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks', body=_tasks('claimed'))
    r = wps.checkin({'cookie': 'wps_sid=abc'})
    assert r.state == 'already'
    assert local_server.received[-1]['path'] == '/api/public/v1/tasks'  # 未发 claim


def test_pending_status_maps_busy(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks', body=_tasks('pending'))
    r = wps.checkin({'cookie': 'wps_sid=abc'})
    assert r.state == 'busy'


def test_missing_task_is_business_error(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks',
                       body={"data": {"tasks": []}})
    r = wps.checkin({'cookie': 'wps_sid=abc'})
    assert r.state == 'error' and '未开通' in r.message


def test_login_page_html_raises_auth_error(wps, local_server):
    # 评审焦点 3：Cookie 失效典型形态=重定向登录页 HTML
    local_server.route('GET', '/api/public/v1/tasks',
                       raw='<html>登录</html>', content_type='text/html')
    with pytest.raises(OpError) as exc:
        wps.checkin({'cookie': 'bad'})
    assert exc.value.kind == 'auth' and 'Cookie' in str(exc.value)


def test_401_raises_auth_error(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks',
                       body={"message": "unauthorized"}, status=401)
    with pytest.raises(OpError) as exc:
        wps.checkin({'cookie': 'bad'})
    assert exc.value.kind == 'auth'


def test_sends_cookie_and_referer_headers(wps, local_server):
    local_server.route('GET', '/api/public/v1/tasks', body=_tasks('claimed'))
    wps.checkin({'cookie': 'wps_sid=abc'})
    headers = local_server.received[-1]['headers']
    assert headers['Cookie'] == 'wps_sid=abc'
    assert 'lingxi' in headers['Referer'] or local_server.base in headers['Referer']


def test_credits_returns_total_balance(wps, local_server):
    local_server.route('GET', '/api/public/v1/credits/balance',
                       body={"data": {"total_balance": 2592}})
    assert wps.credits({'cookie': 'wps_sid=abc'}) == '2592'
