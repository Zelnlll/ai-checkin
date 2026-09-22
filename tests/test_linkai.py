import pytest

from app.http import OpError
import app.platforms.linkai as m
from app.platforms.linkai import LinkaiAdapter


def _tasks(done):
    return {"success": True, "code": 200, "data": {"categories": [
        {"code": "DAILY", "tasks": [
            {"code": "INVITE", "done": False},
            {"code": "SIGN", "title": "每日签到", "done": done},
        ]}]}}


@pytest.fixture
def lk(local_server, monkeypatch):
    monkeypatch.setattr(m, 'LINKAI_BASE', local_server.base)
    return LinkaiAdapter()


def test_sign_task_done_skips_signin_request(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body=_tasks(True))
    r = lk.checkin({'token': 'jwt'})
    assert r.state == 'already'
    assert [x for x in local_server.received if 'sign/in' in x['path']] == []


def test_signin_success_returns_ok_with_score(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body=_tasks(False))
    local_server.route('GET', '/api/chat/web/app/user/sign/in',
                       body={"success": True, "code": 200, "data": {"score": 43}})
    r = lk.checkin({'token': 'jwt'})
    assert r.state == 'ok' and '43' in r.reward


def test_signin_success_random_score(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body=_tasks(False))
    local_server.route('GET', '/api/chat/web/app/user/sign/in',
                       body={"success": True, "code": 200, "data": {}})
    r = lk.checkin({'token': 'jwt'})
    assert r.state == 'ok' and '随机' in r.message


def test_code_870_with_done_task_maps_already(lk, local_server):
    """用户实测：870=今日已签（benefits 已到账），任务复核 done 即判 already。"""
    seq = [_tasks(False), _tasks(True)]   # 预检未签 → 拒签后复核已签
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       dynamic=lambda: seq.pop(0))
    local_server.route('GET', '/api/chat/web/app/user/sign/in',
                       body={"success": False, "code": 870, "message": "签到失败"})
    r = lk.checkin({'token': 'jwt'})
    assert r.state == 'already'


def test_code_870_task_still_open_is_error(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body=_tasks(False))
    local_server.route('GET', '/api/chat/web/app/user/sign/in',
                       body={"success": False, "code": 870, "message": "签到失败"})
    r = lk.checkin({'token': 'jwt'})
    assert r.state == 'error' and '仍未完成' in r.message


def test_401_raises_auth(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body={"message": "unauthorized"}, status=401)
    with pytest.raises(OpError) as exc:
        lk.checkin({'token': 'bad'})
    assert exc.value.kind == 'auth'


def test_credits_returns_score(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/get/balance',
                       body={"success": True, "data": {"score": 1733}})
    assert lk.credits({'token': 'jwt'}) == '1733'


def test_sends_referer_console_and_no_origin(lk, local_server):
    local_server.route('GET', '/api/chat/web/app/user/growth/task/list',
                       body=_tasks(True))
    lk.checkin({'token': 'jwt'})
    headers = {k.lower(): v for k, v in local_server.received[-1]['headers'].items()}
    assert '/console/account' in headers['referer']
    assert 'origin' not in headers
    assert headers['authorization'] == 'Bearer jwt'
