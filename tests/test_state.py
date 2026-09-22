from app.platforms.base import CheckinResult
from app.state import DailyState


def test_mark_ok_makes_done_today_true(tmp_path):
    st = DailyState(tmp_path)
    assert not st.done_today('wps')
    st.mark('wps', CheckinResult('ok', '签到成功 +100', '+100'), '2026-09-22')
    assert st.done_today('wps')
    rec = st.get('wps', '2026-09-22')
    assert rec['state'] == 'ok' and '+100' in (rec['reward'] + rec['message'])


def test_mark_already_counts_as_done(tmp_path):
    st = DailyState(tmp_path)
    st.mark('qoder', CheckinResult('already', '今日已签'), '2026-09-22')
    assert st.done_today('qoder')


def test_error_is_not_done_and_visible_for_alert(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('error', 'Cookie 失效'), '2026-09-22')
    assert not st.done_today('wps')
    assert st.get('wps', '2026-09-22')['state'] == 'error'


def test_yesterday_record_does_not_block_today(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', 'x'), '2026-09-21')
    assert not st.done_today('wps')


def test_corrupt_state_file_recovers_to_empty(tmp_path):
    (tmp_path / 'state.json').write_text('{broken', encoding='utf-8')
    st = DailyState(tmp_path)
    assert not st.done_today('wps')
    st.mark('wps', CheckinResult('ok', 'x'), '2026-09-22')
    assert st.done_today('wps')
