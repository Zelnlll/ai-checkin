import pytest

from app.platforms import ADAPTERS, get_adapter
from app.platforms.base import Adapter, CheckinResult
from app.scheduler import run_all, should_fire
from tests.conftest import FakeConfig, FakeState, FakeStore


class Stub(Adapter):
    platform = 'stub'
    title = 'Stub'
    credential_kind = 'token'

    def checkin(self, creds):
        return CheckinResult('ok', 'stub 成功')


@pytest.fixture
def stub_registered():
    ADAPTERS['stub'] = Stub()
    yield
    del ADAPTERS['stub']


def test_get_adapter_returns_registered_stub(stub_registered):
    assert get_adapter('stub').platform == 'stub'


def test_should_fire_at_and_after_time():
    assert not should_fire(10 * 60 + 4, (10, 5))
    assert should_fire(10 * 60 + 5, (10, 5))
    assert should_fire(23 * 60, (10, 5))


def test_done_platform_is_skipped_without_request(stub_registered):
    calls = []
    outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                       state=FakeState(done={'stub'}), config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda *a: calls.append(a))
    assert outcomes[0].result.state == 'already'
    assert '今日已完成' in outcomes[0].result.message
    assert calls == []


def test_missing_credential_reports_error(stub_registered):
    def never(*a):
        raise AssertionError('run_platform 不应被调用')

    outcomes = run_all(['stub'], store=FakeStore({}), state=FakeState(),
                       config=FakeConfig(), today='2026-09-22',
                       now_minutes=10 * 60 + 6, run_platform=never)
    assert outcomes[0].result.state == 'error'
    assert '凭证' in outcomes[0].result.message


def test_pending_platform_runs_and_marks_state(stub_registered):
    state = FakeState()
    outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda adapter, creds, cfg: CheckinResult('ok', '签到成功 +500', '+500'))
    assert outcomes[0].result.state == 'ok'
    assert state.marked == [('stub', 'ok')]


def test_failed_platform_is_not_marked_done(stub_registered):
    state = FakeState()
    outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda adapter, creds, cfg: CheckinResult('error', 'HTTP 500'))
    assert outcomes[0].result.state == 'error'
    assert state.marked == []
