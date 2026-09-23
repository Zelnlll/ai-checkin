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


def test_done_platform_persists_refreshed_balance():
    class StubB(Stub):
        def credits(self, creds):
            return '4321'
    ADAPTERS['stub'] = StubB()
    try:
        state = FakeState(done={'stub'})
        outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                           state=state, config=FakeConfig(),
                           today='2026-09-22', now_minutes=10 * 60 + 6,
                           run_platform=lambda *a: (_ for _ in ()).throw(
                               AssertionError('不应发签到请求')))
        assert outcomes[0].result.balance == '4321'
        assert ('stub', 'already') in state.marked
    finally:
        del ADAPTERS['stub']


def test_done_platform_no_balance_no_mark(stub_registered):
    state = FakeState(done={'stub'})
    run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
            state=state, config=FakeConfig(), today='2026-09-22',
            now_minutes=10 * 60 + 6, run_platform=lambda *a: None)
    assert state.marked == []   # 空余额不得把旧值抹掉


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
    assert [m[1] for m in state.marked] == ['ok', 'ok']   # I5：mark→enrich→再 mark


def test_failed_platform_is_not_marked_done(stub_registered):
    state = FakeState()
    outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda adapter, creds, cfg: CheckinResult('error', 'HTTP 500'))
    assert outcomes[0].result.state == 'error'
    assert state.marked == []


class Cred(Adapter):
    platform = 'cred'
    title = 'Cred'
    credential_kind = 'token'

    def __init__(self, balance='2592'):
        self._balance = balance

    def checkin(self, creds):
        return CheckinResult('ok', '签到成功', '+100 积分')

    def credits(self, creds):
        if self._balance is None:
            raise RuntimeError('余额接口挂了')
        return self._balance


@pytest.fixture
def cred_registered():
    ADAPTERS['cred'] = Cred()
    yield
    del ADAPTERS['cred']


def test_success_result_enriched_with_balance_and_streak(cred_registered):
    state = FakeState(streaks={'cred': 3})
    outcomes = run_all(['cred'], store=FakeStore({'cred': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda a, c, cfg: CheckinResult('ok', '成功', '+1'))
    r = outcomes[0].result
    assert r.balance == '2592' and r.streak == 3


def test_already_skipped_path_also_enriched(cred_registered):
    state = FakeState(done={'cred'}, streaks={'cred': 5})
    outcomes = run_all(['cred'], store=FakeStore({'cred': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=never_call)
    r = outcomes[0].result
    assert r.state == 'already' and r.balance == '2592' and r.streak == 5


def test_credits_failure_does_not_break_flow(monkeypatch):
    ADAPTERS['cred'] = Cred(balance=None)
    try:
        outcomes = run_all(['cred'], store=FakeStore({'cred': {'token': 't'}}),
                           state=FakeState(streaks={'cred': 1}), config=FakeConfig(),
                           today='2026-09-22', now_minutes=10 * 60 + 6,
                           run_platform=lambda a, c, cfg: CheckinResult('ok', '成功', '+1'))
    finally:
        del ADAPTERS['cred']
    r = outcomes[0].result
    assert r.state == 'ok' and r.balance == '' and r.streak == 1


def test_error_result_not_enriched(cred_registered):
    outcomes = run_all(['cred'], store=FakeStore({'cred': {'token': 't'}}),
                       state=FakeState(), config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda a, c, cfg: CheckinResult('error', 'HTTP 500'))
    r = outcomes[0].result
    assert r.balance == '' and r.streak == 0


def never_call(*a):
    raise AssertionError('不应调用')


def test_touch_keepalive_and_read(tmp_path):
    from app.state import DailyState
    st = DailyState(tmp_path)
    st.touch_keepalive('wps', '2026-09-22')
    assert st.get('wps', '2026-09-22')['keepalive'] == '2026-09-22'
    st.mark('wps', CheckinResult('ok', '成功', '+1'), '2026-09-22')
    st.touch_keepalive('wps', '2026-09-22')
    rec = st.get('wps', '2026-09-22')
    assert rec['state'] == 'ok' and rec['keepalive'] == '2026-09-22'


def test_run_keepalive_pings_credentialed_platforms(cred_registered):
    from app.scheduler import run_keepalive
    calls = []

    class PingCred(Cred):
        def credits(self, creds):
            calls.append(creds['token'])
            return '100'

    ADAPTERS['cred'] = PingCred()
    state = FakeState()
    result = run_keepalive(FakeStore({'cred': {'token': 't1'}}), state,
                           ['cred', 'wps'], today='2026-09-22')
    assert result == {'cred': True} and calls == ['t1']   # wps 无凭证跳过


def test_streak_includes_today_on_first_checkin(cred_registered, tmp_path):
    """I5 回归：真实 DailyState 下，连续第 N 天签到应显示 N（含今天）。"""
    import datetime as dt
    from app.credentials import CredentialStore
    from app.state import DailyState
    state = DailyState(tmp_path)
    store = CredentialStore(tmp_path, {'cred'})
    store.save('cred', {'token': 't'})
    today = dt.date.today()
    state.mark('cred', CheckinResult('ok', 'x'), (today - dt.timedelta(days=1)).isoformat())
    outcomes = run_all(['cred'], store=store, state=state, config=FakeConfig(),
                       today=today.isoformat(), now_minutes=10 * 60 + 6,
                       run_platform=lambda a, c, cfg: CheckinResult('ok', '成功', '+1'))
    assert outcomes[0].result.streak == 2      # 昨天+今天=2
