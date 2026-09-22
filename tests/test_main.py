import datetime as dt

import pytest

from app.config import Config
from app.credentials import CredentialStore
from app.main import cmd_run_once, due_to_run
from app.platforms import ADAPTERS
from app.platforms.base import Adapter, CheckinResult
from app.scheduler import CheckinOutcome
from app.state import DailyState


class Stub(Adapter):
    platform = 'stub'
    title = 'Stub'
    credential_kind = 'token'

    def checkin(self, creds):
        return CheckinResult('ok', 'stub 成功', '+1')


@pytest.fixture
def stub_registered():
    ADAPTERS['stub'] = Stub()
    yield
    del ADAPTERS['stub']


@pytest.fixture
def cfg(tmp_path):
    return Config(checkin_time=(10, 5), retry_times=0,
                  wecom_webhook='', data_dir=tmp_path)


def test_five_platforms_registered():
    assert {'wps', 'dazi', 'minimax', 'qoder', 'modelscope'} <= set(ADAPTERS)


def test_due_to_run_true_when_time_passed_and_not_run():
    now = dt.datetime(2026, 9, 22, 10, 6)
    assert due_to_run(now, Config((10, 5), 3, '', None), None) is True


def test_due_to_run_false_before_time():
    now = dt.datetime(2026, 9, 22, 10, 4)
    assert due_to_run(now, Config((10, 5), 3, '', None), None) is False


def test_due_to_run_false_when_already_ran_today():
    now = dt.datetime(2026, 9, 22, 12, 0)
    assert due_to_run(now, Config((10, 5), 3, '', None), '2026-09-22') is False


def test_run_once_pushes_summary_and_marks_state(cfg, stub_registered):
    store = CredentialStore(cfg.data_dir, {'stub'})
    store.save('stub', {'token': 't'})
    state = DailyState(cfg.data_dir)
    pushed = []

    class FakeNotifier:
        def push(self, outcomes, today):
            pushed.append(outcomes)
            return True

    outcomes = cmd_run_once(cfg, platforms=['stub'], store=store, state=state,
                            notifier=FakeNotifier(),
                            runner_fn=lambda adapter, creds, config:
                            CheckinResult('ok', '签到成功', '+1'))
    assert outcomes[0].result.state == 'ok'
    assert len(pushed) == 1 and pushed[0][0].platform == 'stub'
    assert state.done_today('stub')


def test_run_once_skips_done_platform_without_request(cfg, stub_registered):
    store = CredentialStore(cfg.data_dir, {'stub'})
    store.save('stub', {'token': 't'})
    state = DailyState(cfg.data_dir)
    today = dt.date.today().isoformat()
    state.mark('stub', CheckinResult('ok', '早先完成'), today)
    called = []

    class FakeNotifier:
        def push(self, outcomes, today):
            return True

    outcomes = cmd_run_once(cfg, platforms=['stub'], store=store, state=state,
                            notifier=FakeNotifier(),
                            runner_fn=lambda *a: called.append(a))
    assert called == []
    assert outcomes[0].result.state == 'already'


def test_run_once_selects_app_notifier_when_corpid_configured(cfg, stub_registered, monkeypatch):
    from app.notify_app import WeComAppNotifier
    from app.notify import WeComNotifier
    from app.main import choose_notifier
    app_cfg = Config(cfg.checkin_time, cfg.retry_times, '', cfg.data_dir,
                     wecom_corp_id='ww', wecom_corp_secret='s', wecom_agent_id=1,
                     wecom_to_user='u')
    assert isinstance(choose_notifier(app_cfg), WeComAppNotifier)
    assert isinstance(choose_notifier(cfg), WeComNotifier)   # 无 corpid → 群机器人


def test_due_to_run_retries_pending_rounds():
    cfg10 = Config((10, 5), 3, '', None)
    now = dt.datetime(2026, 9, 22, 11, 0)
    # 首轮 10:05 跑过仍有 pending，超 30 分钟 → 补跑
    assert due_to_run(now, cfg10, '2026-09-22 1 10:05') is True
    # 距上次不足 30 分钟 → 等待
    assert due_to_run(dt.datetime(2026, 9, 22, 10, 20), cfg10,
                      '2026-09-22 1 10:05') is False
    # 全部完成 → 当天不再跑
    assert due_to_run(now, cfg10, '2026-09-22 done') is False
    # 轮次用完 → 不再跑
    assert due_to_run(now, cfg10, '2026-09-22 6 10:05') is False
    # 旧格式（纯日期）向后兼容视为 done
    assert due_to_run(now, cfg10, '2026-09-22') is False
    # 昨天的记录 → 今天到点照跑
    assert due_to_run(now, cfg10, '2026-09-21 done') is True


def test_next_marker_counts_rounds_and_done():
    from app.main import next_marker
    now = dt.datetime(2026, 9, 22, 10, 5)
    outcomes = [CheckinOutcome('wps', CheckinResult('ok', 'x')),
                CheckinOutcome('dazi', CheckinResult('busy', 'y'))]
    assert next_marker(now, '2026-09-22 1 10:05', outcomes) == '2026-09-22 2 10:05'
    outcomes_done = [CheckinOutcome('wps', CheckinResult('ok', 'x'))]
    assert next_marker(now, '2026-09-22 1 10:05', outcomes_done) == '2026-09-22 done'
    assert next_marker(now, None, None) == '2026-09-22 1 10:05'   # 首轮异常也计轮次


def test_next_marker_exception_keeps_pending():
    from app.main import next_marker
    now = dt.datetime(2026, 9, 22, 10, 5)
    assert next_marker(now, '2026-09-22 2 10:05', None) == '2026-09-22 3 10:05'


class _PushSpy:
    def __init__(self):
        self.pushed = []

    def push(self, outcomes, today):
        self.pushed.append(today)
        return True


def _patch_pusher(monkeypatch):
    spy = _PushSpy()
    monkeypatch.setattr('app.main.choose_notifier', lambda cfg: spy)
    return spy


def test_push_only_on_signature_change(tmp_path, monkeypatch):
    from app.main import _push_if_changed
    cfg = Config((10, 5), 3, '', tmp_path)
    spy = _patch_pusher(monkeypatch)
    ok = [CheckinOutcome('wps', CheckinResult('ok', 'x')),
          CheckinOutcome('dazi', CheckinResult('error', 'y'))]
    _push_if_changed(cfg, ok)                       # 首轮必发
    _push_if_changed(cfg, ok)                       # 状态没变 → 不发
    assert len(spy.pushed) == 1
    better = [CheckinOutcome('wps', CheckinResult('ok', 'x')),
              CheckinOutcome('dazi', CheckinResult('ok', 'y'))]
    _push_if_changed(cfg, better)                   # dazi 变 ok → 发终态卡
    assert len(spy.pushed) == 2
    _push_if_changed(cfg, better)                   # 又没变 → 不发
    assert len(spy.pushed) == 2


def test_outcomes_signature_stable():
    from app.main import outcomes_signature
    a = [CheckinOutcome('wps', CheckinResult('ok', 'x')),
         CheckinOutcome('dazi', CheckinResult('error', 'y'))]
    b = list(reversed(a))
    assert outcomes_signature(a) == outcomes_signature(b)
