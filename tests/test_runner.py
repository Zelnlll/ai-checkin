import json

import pytest

from app.http import OpError
from app.platforms.base import Adapter, CheckinResult
from app.runner import run_platform


class Flaky(Adapter):
    platform = 'f'
    title = 'F'
    credential_kind = 'token'

    def __init__(self, script):
        self.script = list(script)
        self.n = 0

    def checkin(self, creds):
        item = self.script[self.n]
        self.n += 1
        if isinstance(item, Exception):
            raise item
        return item


def test_busy_then_success_retries_until_ok():
    a = Flaky([CheckinResult('busy', '拥挤'), CheckinResult('ok', '签到成功 +500', '+500')])
    r = run_platform(a, {}, retry_times=3, sleep=lambda s: None)
    assert r.state == 'ok' and a.n == 2


def test_auth_error_never_retries():
    a = Flaky([OpError('401 unauthorized', kind='auth')])
    r = run_platform(a, {}, retry_times=3, sleep=lambda s: None)
    assert r.state == 'error' and '凭证失效' in r.message and a.n == 1


def test_exhausts_retries_returns_last_error():
    a = Flaky([OpError('超时', kind='network')] * 4)
    r = run_platform(a, {}, retry_times=3, sleep=lambda s: None)
    assert r.state == 'error' and a.n == 4


def test_backoff_is_exponential():
    a = Flaky([CheckinResult('busy', 'x')] * 3 + [CheckinResult('ok', 'y')])
    slept = []
    run_platform(a, {}, retry_times=3, sleep=slept.append)
    assert slept == [10, 20, 40]


def test_ok_result_is_returned_as_is():
    a = Flaky([CheckinResult('ok', '签到成功', '+100 积分')])
    r = run_platform(a, {}, retry_times=3, sleep=lambda s: None)
    assert r.state == 'ok' and r.reward == '+100 积分'


def test_each_attempt_is_logged(tmp_path):
    log = tmp_path / 'requests.log'
    a = Flaky([CheckinResult('busy', '拥挤'), CheckinResult('ok', '成功')])
    run_platform(a, {}, retry_times=3, sleep=lambda s: None, log_path=log)
    lines = [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines()]
    assert len(lines) == 2
    assert lines[0]['platform'] == 'f' and lines[0]['state'] == 'busy'
    assert lines[1]['state'] == 'ok'
