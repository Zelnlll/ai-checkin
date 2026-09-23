import datetime as dt

from app.platforms.base import CheckinResult
from app.state import DailyState

TODAY = dt.date.today().isoformat()


def test_mark_ok_makes_done_today_true(tmp_path):
    st = DailyState(tmp_path)
    assert not st.done_today('wps')
    st.mark('wps', CheckinResult('ok', '签到成功 +100', '+100'), TODAY)
    assert st.done_today('wps')
    rec = st.get('wps', TODAY)
    assert rec['state'] == 'ok' and '+100' in (rec['reward'] + rec['message'])


def test_mark_already_counts_as_done(tmp_path):
    st = DailyState(tmp_path)
    st.mark('qoder', CheckinResult('already', '今日已签'), TODAY)
    assert st.done_today('qoder')


def test_error_is_not_done_and_visible_for_alert(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('error', 'Cookie 失效'), TODAY)
    assert not st.done_today('wps')
    assert st.get('wps', TODAY)['state'] == 'error'


def test_yesterday_record_does_not_block_today(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', 'x'), '2026-09-21')
    assert not st.done_today('wps')


def test_corrupt_state_file_recovers_to_empty(tmp_path):
    (tmp_path / 'state.json').write_text('{broken', encoding='utf-8')
    st = DailyState(tmp_path)
    assert not st.done_today('wps')
    st.mark('wps', CheckinResult('ok', 'x'), TODAY)
    assert st.done_today('wps')


def test_streak_counts_consecutive_days(tmp_path):
    from app.platforms.base import CheckinResult as R
    st = DailyState(tmp_path)
    for day in ('2026-09-20', '2026-09-21', '2026-09-22'):
        st.mark('wps', R('ok', 'x'), day)
    assert st.streak('wps', '2026-09-22') == 3


def test_streak_breaks_on_gap(tmp_path):
    from app.platforms.base import CheckinResult as R
    st = DailyState(tmp_path)
    st.mark('wps', R('ok', 'x'), '2026-09-19')
    st.mark('wps', R('ok', 'x'), '2026-09-21')
    st.mark('wps', R('ok', 'x'), '2026-09-22')
    assert st.streak('wps', '2026-09-22') == 2


def test_streak_from_yesterday_when_today_pending(tmp_path):
    from app.platforms.base import CheckinResult as R
    st = DailyState(tmp_path)
    st.mark('wps', R('ok', 'x'), '2026-09-20')
    st.mark('wps', R('ok', 'x'), '2026-09-21')
    assert st.streak('wps', '2026-09-22') == 2   # 今天还没签，连签按昨天截止


def test_streak_zero_when_never(tmp_path):
    assert DailyState(tmp_path).streak('wps', '2026-09-22') == 0


def test_mark_persists_balance_and_streak(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', '成功', '+100', balance='2592', streak=3),
            '2026-09-22')
    rec = st.get('wps', '2026-09-22')
    assert rec['balance'] == '2592' and rec['streak'] == 3
