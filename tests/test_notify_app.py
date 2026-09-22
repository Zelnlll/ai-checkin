import pytest

import app.notify_app as na
from app.config import Config
from app.notify_app import WeComAppNotifier
from app.platforms import ADAPTERS
from app.platforms.base import Adapter, CheckinResult
from app.scheduler import CheckinOutcome


class _Wps(Adapter):
    platform = 'wps'
    title = 'WPS 灵犀'
    credential_kind = 'cookie'

    def checkin(self, creds):
        return CheckinResult('ok', 'x')


@pytest.fixture
def outcomes():
    ADAPTERS['wps'] = _Wps()
    yield [CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分'))]
    del ADAPTERS['wps']


@pytest.fixture
def cfg(tmp_path):
    return Config((10, 5), 3, '', tmp_path,
                  wecom_corp_id='ww123', wecom_corp_secret='sec',
                  wecom_agent_id=1000002, wecom_to_user='zhangsan')


@pytest.fixture
def server(local_server, monkeypatch):
    monkeypatch.setattr(na, 'API_BASE', local_server.base)
    local_server.route('GET', '/gettoken',
                       body={"errcode": 0, "access_token": 'tok-1',
                             "expires_in": 7200})
    return local_server


def sent_bodies(server):
    import json
    return [json.loads(x['body']) for x in server.received
            if x['path'].startswith('/message/send')]


def test_push_sends_card_with_agentid_and_touser(server, cfg, outcomes):
    server.route('POST', '/message/send', body={"errcode": 0, "errmsg": 'ok'})
    assert WeComAppNotifier(cfg).push(outcomes, '2026-09-22') is True
    body = sent_bodies(server)[0]
    assert body['agentid'] == 1000002
    assert body['touser'] == 'zhangsan'
    assert body['msgtype'] == 'template_card'
    assert 'WPS 灵犀' in str(body['template_card'])


def test_token_cached_between_pushes(server, cfg, outcomes):
    server.route('POST', '/message/send', body={"errcode": 0})
    n = WeComAppNotifier(cfg)
    n.push(outcomes, '2026-09-22')
    n.push(outcomes, '2026-09-22')
    tokens = [x for x in server.received if x['path'].startswith('/gettoken')]
    assert len(tokens) == 1
    sends = [x for x in server.received if x['path'].startswith('/message/send')]
    assert 'access_token=tok-1' in sends[0]['path']


def test_invalid_token_refreshed_and_retried_once(server, cfg, outcomes):
    seq = [{"errcode": 40001, "errmsg": 'invalid token'}, {"errcode": 0}]
    calls = []

    def dynamic():
        calls.append(1)
        return seq[min(len(calls) - 1, 1)]
    server.route('POST', '/message/send', dynamic=dynamic)
    assert WeComAppNotifier(cfg).push(outcomes, '2026-09-22') is True
    tokens = [x for x in server.received if x['path'].startswith('/gettoken')]
    assert len(tokens) == 2          # 失效后重新换取，且只重试一次


def test_chatid_target_when_configured(server, tmp_path, outcomes):
    server.route('POST', '/message/send', body={"errcode": 0})
    cfg = Config((10, 5), 3, '', tmp_path, wecom_corp_id='ww', wecom_corp_secret='s',
                 wecom_agent_id=1, wecom_chat_id='chat-9')
    WeComAppNotifier(cfg).push(outcomes, '2026-09-22')
    body = sent_bodies(server)[0]
    assert body['chatid'] == 'chat-9' and 'touser' not in body


def test_missing_config_returns_false(cfg, outcomes):
    bad = Config((10, 5), 3, '', cfg.data_dir)   # 无 corpid
    assert WeComAppNotifier(bad).push(outcomes, '2026-09-22') is False


def test_gettoken_failure_returns_false(server, cfg, outcomes):
    server.route('GET', '/gettoken', body={"errcode": 40013, "errmsg": 'invalid corpid'})
    assert WeComAppNotifier(cfg).push(outcomes, '2026-09-22') is False
