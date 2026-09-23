import pytest

from app.platforms import ADAPTERS, get_adapter
from app.platforms.base import Adapter, CheckinResult
from app.scheduler import balance_due, run_all, run_balance, should_fire
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
    ADAPTERS.pop('stub', None)   # 测试体内可能已自行替换/删除


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
        state = FakeState(done={'stub'}, recs={
            ('stub', '2026-09-22'): {'state': 'ok', 'message': '签到成功 +400',
                                     'reward': '+400'}})
        outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                           state=state, config=FakeConfig(),
                           today='2026-09-22', now_minutes=10 * 60 + 6,
                           run_platform=lambda *a: (_ for _ in ()).throw(
                               AssertionError('不应发签到请求')))
        assert outcomes[0].result.balance == '4321'
        assert ('stub', 'ok') in state.marked   # 回写沿用原状态 ok，不降级成 already
        marked = state.results[-1][1]   # 回写不得覆盖原 state/message/reward
        assert marked.state == 'ok' and marked.message == '签到成功 +400'
        assert marked.reward == '+400' and marked.balance == '4321'
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


class StubBal(Stub):
    balance = '123'

    def credits(self, creds):
        if self.balance is None:
            raise RuntimeError('boom')
        return self.balance


def test_run_balance_updates_existing_record(stub_registered):
    ADAPTERS['stub'] = StubBal()
    try:
        state = FakeState(done={'stub'}, recs={
            ('stub', '2026-09-23'): {'state': 'ok', 'message': '成功 +250',
                                     'reward': '+250', 'balance': '500'}})
        out = run_balance(FakeStore({'stub': {'token': 't'}}), state,
                          ['stub'], '2026-09-23')
        assert out == {'stub': '123'}
        marked = state.results[-1][1]
        assert marked.balance == '123' and marked.state == 'ok'
        assert marked.message == '成功 +250' and marked.reward == '+250'
    finally:
        del ADAPTERS['stub']


def test_run_balance_no_record_no_mark(stub_registered):
    ADAPTERS['stub'] = StubBal()
    try:
        state = FakeState()          # 今日无记录：不得抢先造 done 记录破坏幂等
        out = run_balance(FakeStore({'stub': {'token': 't'}}), state,
                          ['stub'], '2026-09-23')
        assert out == {'stub': '123'} and state.marked == []
    finally:
        del ADAPTERS['stub']


def test_run_balance_skips_missing_creds_and_errors(stub_registered):
    ADAPTERS['stub'] = StubBal()
    ADAPTERS['bad'] = type('Bad', (StubBal,), {'platform': 'bad'})()
    try:
        state = FakeState(done={'stub'}, recs={('stub', 'd'): {'state': 'ok'}})
        out = run_balance(FakeStore({}), state, ['stub', 'bad'], 'd')
        assert out == {} and state.marked == []
        ADAPTERS['stub'].balance = None   # credits 抛异常也不炸
        state2 = FakeState(done={'stub'}, recs={('stub', 'd'): {'state': 'ok'}})
        out = run_balance(FakeStore({'stub': {'token': 't'}}), state2,
                          ['stub'], 'd')
        assert out == {} and state2.marked == []
    finally:
        del ADAPTERS['stub']
        del ADAPTERS['bad']


def test_balance_due_boundaries():
    assert not balance_due(1000, None, 60)          # 未初始化不触发
    assert balance_due(4600, 1000, 60)
    assert not balance_due(3000, 1000, 60)
