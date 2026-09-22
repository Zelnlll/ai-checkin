import pytest

from app.http import OpError
import app.platforms.modelscope as m
from app.platforms.modelscope import ModelscopeAdapter


def _rules(earned_daily, earned_bind=0):
    return {"success": True, "data": [
        {"rule_key": "daily_active", "amount": 200,
         "today_earned_amount": earned_daily},
        {"rule_key": "aliyun_bindlogin", "amount": 50,
         "today_earned_amount": earned_bind},
        {"rule_key": "interaction_like", "amount": 2,
         "today_earned_amount": 99},   # 非日常规则不参与求和
    ]}


@pytest.fixture
def ms(local_server, monkeypatch):
    monkeypatch.setattr(m, 'MS_BASE', local_server.base)
    monkeypatch.setattr(m, '_sleep', lambda s: None)
    monkeypatch.setattr(m, 'trigger_visit', lambda cookie: None)
    return ModelscopeAdapter()


CREDS = {'token': 'ms-test-token', 'cookie': 'm_session_id=x'}


def test_granted_today_maps_already_with_reward(ms, local_server):
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules',
                       body=_rules(200, 50))
    r = ms.checkin(CREDS)
    assert r.state == 'already' and '250' in r.reward


def test_trigger_then_recheck_finds_grant_maps_ok(ms, local_server, monkeypatch):
    seq = [_rules(0, 0), _rules(200, 50)]
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules',
                       dynamic=lambda: seq.pop(0))
    calls = []
    monkeypatch.setattr(m, 'trigger_visit',
                        lambda cookie: calls.append(cookie))
    r = ms.checkin(CREDS)
    assert r.state == 'ok' and '250' in r.reward
    assert calls == ['m_session_id=x']       # 触发器带 Cookie 被调用


def test_still_zero_after_trigger_is_busy_not_error(ms, local_server):
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules', body=_rules(0, 0))
    r = ms.checkin(CREDS)
    assert r.state == 'busy' and '未发放' in r.message   # 评审焦点 2


def test_success_false_is_error(ms, local_server):
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules',
                       body={"success": False, "message": "rate limited"})
    r = ms.checkin(CREDS)
    assert r.state == 'error' and 'rate limited' in r.message


def test_401_raises_auth(ms, local_server):
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules',
                       body={"message": "unauthorized"}, status=401)
    with pytest.raises(OpError) as exc:
        ms.checkin(CREDS)
    assert exc.value.kind == 'auth'


def test_missing_token_raises_auth():
    with pytest.raises(OpError) as exc:
        ModelscopeAdapter().checkin({'token': ''})
    assert exc.value.kind == 'auth'


def test_sends_bearer_header(ms, local_server):
    local_server.route('GET', '/openapi/v1/magicubes/earn/rules', body=_rules(200, 50))
    ms.checkin(CREDS)
    headers = local_server.received[-1]['headers']
    assert headers['Authorization'] == 'Bearer ms-test-token'
