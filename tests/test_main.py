import datetime as dt

import pytest

from app.config import Config
from app.credentials import CredentialStore
from app.main import cmd_run_once, due_to_run
from app.platforms import ADAPTERS
from app.platforms.base import Adapter, CheckinResult
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
