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


def test_done_platform_skip_refreshes_balance_without_mark():
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
        assert state.balances == [('stub', '4321')]
        assert state.results == []      # 绝不 mark：不伪造/覆盖 state 与 at
        assert ('stub', 'keepalive') in state.marked
    finally:
        del ADAPTERS['stub']


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


def test_failed_platform_marked_but_not_done(stub_registered):
    state = FakeState()
    outcomes = run_all(['stub'], store=FakeStore({'stub': {'token': 't'}}),
                       state=state, config=FakeConfig(),
                       today='2026-09-22', now_minutes=10 * 60 + 6,
                       run_platform=lambda adapter, creds, cfg: CheckinResult('error', 'HTTP 500'))
    assert outcomes[0].result.state == 'error'
    assert state.marked == [('stub', 'error')]   # 失败落盘供面板显示原因
    assert not state.done_today('stub')          # 但绝不算"已完成"


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


def test_run_balance_writes_balance_and_keepalive(stub_registered):
    ADAPTERS['stub'] = StubBal()
    try:
        state = FakeState()
        out = run_balance(FakeStore({'stub': {'token': 't'}}), state,
                          ['stub'], '2026-09-23')
        assert out == {'stub': '123'}
        assert state.balances == [('stub', '123')]
        assert state.results == []              # 绝不伪造 state
        assert ('stub', 'keepalive') in state.marked
    finally:
        del ADAPTERS['stub']


def test_run_balance_skips_missing_creds_and_errors(stub_registered):
    ADAPTERS['stub'] = StubBal()
    try:
        state = FakeState()
        out = run_balance(FakeStore({}), state, ['stub', 'nosuch'], 'd')
        assert out == {} and state.balances == []
        ADAPTERS['stub'].balance = None   # credits 抛异常也不炸
        state2 = FakeState()
        out = run_balance(FakeStore({'stub': {'token': 't'}}), state2,
                          ['stub'], 'd')
        assert out == {} and state2.balances == []
    finally:
        del ADAPTERS['stub']


def test_balance_due_boundaries():
    assert not balance_due(1000, None, 60)          # 未初始化不触发
    assert balance_due(4600, 1000, 60)
    assert not balance_due(3000, 1000, 60)


def test_run_balance_caches_earliest_expiring(stub_registered):
    ADAPTERS['stub'] = StubBal()
    StubBal.breakdown = lambda self, creds: [
        {'tag': '资源包', 'name': '签到包', 'amount': '100',
         'expire': '7天后过期（10-01）'},
        {'tag': '资源包', 'name': '长期包', 'amount': '50', 'expire': '长期有效'},
    ]
    try:
        state = FakeState()
        run_balance(FakeStore({'stub': {'token': 't'}}), state, ['stub'], 'd')
        assert state.expirings == [('stub', '100 · 10-01到期')]
    finally:
        del StubBal.breakdown
        del ADAPTERS['stub']


def test_run_balance_no_breakdown_no_expiring(stub_registered):
    ADAPTERS['stub'] = StubBal()
    try:
        state = FakeState()
        run_balance(FakeStore({'stub': {'token': 't'}}), state, ['stub'], 'd')
        assert state.expirings == []
    finally:
        del ADAPTERS['stub']


# ---------- 多账号 ----------

def test_run_all_two_accounts_aggregates(stub_registered):
    class Stub2(Stub):
        def credits(self, creds):
            return creds.get('bal')
    ADAPTERS['stub'] = Stub2()
    calls = []

    def runner(adapter, creds, config):
        calls.append(creds['token'])
        return CheckinResult('ok', '成', '+100 积分')
    state = FakeState()
    store = FakeStore({'stub': [{'token': 't1', 'id': 'main', 'bal': '500'},
                                {'token': 't2', 'id': 'ab12', 'bal': '500'}]})
    out = run_all(['stub'], store=store, state=state, config=FakeConfig(),
                  today='d', now_minutes=0, run_platform=runner)
    assert calls == ['t1', 't2']
    assert ('stub', 'ok') in state.marked and ('stub#ab12', 'ok') in state.marked
    r = out[0].result
    assert r.state == 'ok' and '2/2' in r.message
    assert r.reward == '+200 积分' and r.balance == '1000'
    assert set(out[0].accounts) == {'main', 'ab12'}


def test_run_all_skips_done_account_only(stub_registered):
    ADAPTERS['stub'] = Stub()
    calls = []

    def runner(adapter, creds, config):
        calls.append(creds['token'])
        return CheckinResult('ok', '成', '+100 积分')
    state = FakeState(done={('stub', 'main')})
    store = FakeStore({'stub': [{'token': 't1', 'id': 'main'},
                                {'token': 't2', 'id': 'ab12'}]})
    out = run_all(['stub'], store=store, state=state, config=FakeConfig(),
                  today='d', now_minutes=0, run_platform=runner)
    assert calls == ['t2']                    # 只补未签的账号
    assert out[0].result.state == 'ok' and '2/2' in out[0].result.message


def test_run_all_partial_failure_names_account(stub_registered):
    ADAPTERS['stub'] = Stub()

    def runner(adapter, creds, config):
        if creds['token'] == 't2':
            return CheckinResult('error', 'token失效')
        return CheckinResult('ok', '成', '+100 积分')
    store = FakeStore({'stub': [{'token': 't1', 'id': 'main'},
                                {'token': 't2', 'id': 'ab12',
                                 'label': '小号'}]})
    out = run_all(['stub'], store=store, state=FakeState(),
                  config=FakeConfig(),
                  today='d', now_minutes=0, run_platform=runner)
    r = out[0].result
    assert r.state == 'error' and '1/2' in r.message and '小号：token失效' in r.message


def test_run_balance_per_accounts_sums(stub_registered):
    ADAPTERS['stub'] = StubBal()
    state = FakeState()
    store = FakeStore({'stub': [{'token': 't1', 'id': 'main'},
                                {'token': 't2', 'id': 'x2'}]})
    out = run_balance(store, state, ['stub'], 'd')
    assert ('stub', '123') in state.balances and ('stub#x2', '123') in state.balances
    assert out == {'stub': '246'}
