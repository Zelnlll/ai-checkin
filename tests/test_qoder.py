import pytest

from app.http import OpError
import app.platforms.qoder as m
from app.platforms.qoder import QoderAdapter


def _campaigns(items):
    return {"campaigns": items}


@pytest.fixture
def qd(local_server, monkeypatch):
    monkeypatch.setattr(m, 'QODER_OPENAPI', local_server.base)
    return QoderAdapter()


CLAIMABLE = [{"campaignId": 77, "campaignKey": "daily_credits",
              "actionType": "CLAIM_BENEFIT", "claimStatus": "CLAIMABLE"}]


def test_claimable_campaign_claims_and_returns_ok(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns', body=_campaigns(CLAIMABLE))
    local_server.route('POST', '/sash/api/v1/me/campaigns/77/claim',
                       body={"benefit": {"amount": 100}})
    r = qd.checkin({'token': 'jwt'})
    assert r.state == 'ok' and '100' in r.reward


def test_only_claimed_maps_already(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns',
                       body=_campaigns([{"campaignId": 1, "actionType": 'CLAIM_BENEFIT',
                                          "claimStatus": 'CLAIMED'}]))
    r = qd.checkin({'token': 'jwt'})
    assert r.state == 'already' and '已领取' in r.message


def test_no_campaign_is_error_with_hint(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns', body=_campaigns([]))
    r = qd.checkin({'token': 'jwt'})
    assert r.state == 'error' and '10:00' in r.message


def test_red_line_never_touches_legacy_daily_check_in(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns', body=_campaigns(CLAIMABLE))
    local_server.route('POST', '/sash/api/v1/me/campaigns/77/claim',
                       body={"benefit": {"amount": 100}})
    qd.checkin({'token': 'jwt'})
    paths = [x['path'] for x in local_server.received]
    assert all('daily-check-in' not in p for p in paths)   # 409 恒返端点绝不请求


def test_409_on_claim_is_error_not_already(qd, local_server):
    # 评审焦点 1：任何 409 都不得被解读为"已签到"
    local_server.route('GET', '/sash/api/v1/me/campaigns', body=_campaigns(CLAIMABLE))
    local_server.route('POST', '/sash/api/v1/me/campaigns/77/claim',
                       body={"message": "AlreadyExists"}, status=409)
    r = qd.checkin({'token': 'jwt'})
    assert r.state == 'error'


def test_401_raises_auth(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns',
                       body={"message": "unauthorized"}, status=401)
    with pytest.raises(OpError) as exc:
        qd.checkin({'token': 'jwt'})
    assert exc.value.kind == 'auth'


def test_bearer_prefix_is_stripped_and_cosy_headers_sent(qd, local_server):
    local_server.route('GET', '/sash/api/v1/me/campaigns', body=_campaigns([]))
    qd.checkin({'token': 'Bearer jwt-token'})
    headers = {k.lower(): v for k, v in local_server.received[-1]['headers'].items()}
    assert headers['authorization'] == 'Bearer jwt-token'
    assert headers['cosy-clienttype'] == '10'
    assert headers['user-agent'] == 'Qoder'
