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


def test_breakdown_lists_packs_sorted_by_expiry(trae, local_server):
    import time
    far = int(time.time()) + 29 * 86400
    mid = int(time.time()) + 20 * 86400
    near = int(time.time()) + 7 * 86400
    # product_id 决定积分池：209=Work，208/221=通用（2026-09-23 实测
    # 通用2950=500+2000+450 / Work2500=2000+500 与官方明细逐项吻合）
    local_server.route(
        'POST', '/trae/api/v2/pay/user_current_entitlement_list',
        body={'user_entitlement_pack_list': [
            {'display_desc': '老用户福利', 'group_name': '用户福利',
             'expire_time': far,
             'entitlement_base_info': {'product_id': 208,
                                       'quota': {'credits_limit': 2000}}},
            {'display_desc': '每周登录奖励', 'group_name': '每月登录',
             'expire_time': near,
             'entitlement_base_info': {'product_id': 221,
                                       'quota': {'credits_limit': 500}}},
            {'display_desc': 'Work福利', 'group_name': '用户福利',
             'expire_time': mid,
             'entitlement_base_info': {'product_id': 209,
                                       'quota': {'credits_limit': 2500}}},
            {'display_desc': '已过期包', 'group_name': '过期',
             'expire_time': int(time.time()) - 86400,
             'entitlement_base_info': {'product_id': 208,
                                       'quota': {'credits_limit': 999}}},
        ]})
    rows = trae.breakdown({'token': 'T', 'host': local_server.base})
    assert [r['amount'] for r in rows] == ['500', '2500', '2000']  # 过期剔除+失效升序
    assert [r['tag'] for r in rows] == ['通用', 'Work', '通用']
    assert rows[0]['name'] == '每月登录'
    assert '7天后过期' in rows[0]['expire']
