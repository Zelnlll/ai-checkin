import pytest

from app.http import OpError
from app.platforms.trae import TraeAdapter

STATUS = '/trae/api/v2/ug/checkin_credits/status'
CLAIM = '/trae/api/v2/ug/checkin_credits/claim'


@pytest.fixture
def trae():
    return TraeAdapter()


def _route_status(ls, body):
    ls.route('POST', STATUS, body=body)


def test_checkin_ok_flow(trae, local_server):
    local_server.route('POST', STATUS,
                       body={'enable': True, 'checked_in': False, 'credits': 200})
    local_server.route('POST', CLAIM,
                       body={'code': 0, 'data': {'credits': 200}})
    r = trae.checkin({'token': 'T', 'host': local_server.base})
    assert r.state == 'ok' and '+200' in r.reward


def test_checkin_already(trae, local_server):
    _route_status(local_server, {'enable': True, 'checked_in': True,
                                 'credits': 150})
    r = trae.checkin({'token': 'T', 'host': local_server.base})
    assert r.state == 'already' and '150' in r.message
    assert r.reward == '+150 积分'      # 面板"今日已得"读 reward


def test_checkin_claim_9004_counts_already(trae, local_server):
    _route_status(local_server, {'enable': True, 'checked_in': False})
    local_server.route('POST', CLAIM,
                       body={'code': 9004, 'message': 'order parameters'})
    assert trae.checkin({'token': 'T', 'host': local_server.base}).state == 'already'


def test_checkin_inactive_activity(trae, local_server):
    _route_status(local_server, {'enable': False})
    r = trae.checkin({'token': 'T', 'host': local_server.base})
    assert r.state == 'error' and '未开启' in r.message


def test_auth_error_on_401(trae, local_server):
    local_server.route('POST', STATUS, status=401, body={})
    with pytest.raises(OpError) as e:
        trae.checkin({'token': 'T', 'host': local_server.base})
    assert e.value.kind == 'auth'


def test_headers_cloud_ide_jwt(trae, local_server):
    _route_status(local_server, {'enable': True, 'checked_in': True})
    trae.checkin({'token': 'T1', 'host': local_server.base, 'region': 'CN',
                  'device_id': 'D9'})
    hdrs = local_server.received[-1]['headers']
    assert hdrs['Authorization'] == 'Cloud-IDE-JWT T1'
    assert hdrs['X-User-Region'] == 'CN'
    assert hdrs.get('X-Device-Id') == 'D9'


def test_credits_reads_entitlement_summary(trae, local_server):
    # 官方余额=usage_summary.total_amount-consumed_amount（2026-09-23 实测 5450=通用2950+Work2500）
    local_server.route(
        'POST', '/trae/api/v2/pay/user_current_entitlement_list',
        body={'usage_summary': {'total_amount': 5450, 'consumed_amount': 0}})
    assert trae.credits({'token': 'T', 'host': local_server.base}) == '5450'
