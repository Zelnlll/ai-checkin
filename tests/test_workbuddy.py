import pytest

from app.http import OpError
from app.platforms.workbuddy import WorkbuddyAdapter

STATUS = '/v2/billing/meter/checkin-activity-status'
CLAIM = '/v2/billing/meter/daily-checkin'


@pytest.fixture
def wb():
    return WorkbuddyAdapter()


CREDS = {'token': 'AT', 'uid': 'U1', 'endpoint': None}


def _creds(ls):
    return {'token': 'AT', 'uid': 'U1', 'endpoint': ls.base}


def test_checkin_ok_flow(wb, local_server):
    local_server.route('POST', STATUS, body={'data': {'today_checked_in': False}})
    local_server.route('POST', CLAIM, body={'credit': 100})
    r = wb.checkin(_creds(local_server))
    assert r.state == 'ok' and '+100' in r.reward


def test_checkin_already_by_status(wb, local_server):
    local_server.route('POST', STATUS,
                       body={'data': {'today_checked_in': True,
                                      'today_credit': 100,
                                      'total_credits': 2500}})
    r = wb.checkin(_creds(local_server))
    assert r.state == 'already' and '2500' in r.message
    assert r.reward == '+100 积分'


def test_checkin_already_by_claim_10001(wb, local_server):
    local_server.route('POST', STATUS, body={'today_checked_in': False})
    local_server.route('POST', CLAIM, status=400,
                       body={'code': 10001, 'msg': '今天已签到，请明天再来'})
    assert wb.checkin(_creds(local_server)).state == 'already'


def test_checkin_claim_null_body_is_already(wb, local_server):
    local_server.route('POST', STATUS, body={'today_checked_in': False})
    local_server.route('POST', CLAIM, raw='null', status=200)
    assert wb.checkin(_creds(local_server)).state == 'already'


def test_business_error(wb, local_server):
    local_server.route('POST', STATUS, body={'today_checked_in': False})
    local_server.route('POST', CLAIM, status=400,
                       body={'code': 20002, 'msg': '活动已结束'})
    r = wb.checkin(_creds(local_server))
    assert r.state == 'error' and '活动已结束' in r.message


def test_auth_on_401(wb, local_server):
    local_server.route('POST', STATUS, status=401, body={})
    with pytest.raises(OpError) as e:
        wb.checkin(_creds(local_server))
    assert e.value.kind == 'auth'


def test_headers(wb, local_server):
    local_server.route('POST', STATUS, body={'today_checked_in': True})
    creds = _creds(local_server)
    creds.update({'enterprise_id': 'E1', 'domain': 'tencent.com'})
    wb.checkin(creds)
    h = local_server.received[-1]['headers']
    assert h['Authorization'] == 'Bearer AT'
    assert h['X-User-Id'] == 'U1'
    assert h['User-Agent'] == 'WorkBuddy'
    assert h['X-Enterprise-Id'] == h['X-Tenant-Id'] == 'E1'
    assert h['X-Domain'] == 'tencent.com'


def test_credits_sums_package_remains(wb, local_server):
    # 官方余额=www.workbuddy.cn summary 各包 CycleRemainCapacity 之和
    # （2026-09-23 实测 4269+485.24+272=5026.24 与官网一致）
    local_server.route('POST', '/billing/meter/get-user-resource-summary',
                       body={'code': 0, 'data': {'Packages': [
                           {'PackageCode': 'A', 'CycleRemainCapacity': '4269'},
                           {'PackageCode': 'B', 'CycleRemainCapacity': '485.24'},
                           {'PackageCode': 'C', 'CycleRemainCapacity': '272'},
                       ]}})
    creds = _creds(local_server)
    creds['web_endpoint'] = local_server.base
    assert wb.credits(creds) == '5026.24'


def test_credits_integer_when_no_decimal(wb, local_server):
    local_server.route('POST', '/billing/meter/get-user-resource-summary',
                       body={'code': 0, 'data': {'Packages': [
                           {'CycleRemainCapacity': '800'}]}})
    creds = _creds(local_server)
    creds['web_endpoint'] = local_server.base
    assert wb.credits(creds) == '800'
