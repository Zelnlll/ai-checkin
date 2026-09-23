import datetime as dt
import json

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


def test_set_balance_merges_without_touching_state_or_at(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('error', '870 真拒签'), TODAY)
    before = st.get('wps', TODAY)
    st.set_balance('wps', TODAY, '500')
    after = st.get('wps', TODAY)
    assert after['balance'] == '500'
    assert after['state'] == 'error' and after['message'] == '870 真拒签'
    assert after['at'] == before['at']      # 上次执行时刻不被余额刷新污染
    assert not st.done_today('wps')


def test_set_balance_creates_balance_only_record(tmp_path):
    st = DailyState(tmp_path)
    st.set_balance('qoder', TODAY, '9')
    rec = st.get('qoder', TODAY)
    assert rec == {'balance': '9'}
    assert not st.done_today('qoder')       # 绝不因余额写入变成"已完成"


def test_set_expiring_merges_only_field(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', 'm', '+1', balance='10'), TODAY)
    before = st.get('wps', TODAY)
    st.set_expiring('wps', TODAY, '1500 · 10-15到期')
    after = st.get('wps', TODAY)
    assert after['expiring'] == '1500 · 10-15到期'
    assert after['state'] == 'ok' and after['balance'] == '10'
    assert after['at'] == before['at']


# ---------- 多账号 ----------

def test_mark_per_account_and_legacy_main_key(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', '主'), TODAY, account='main')
    st.mark('wps', CheckinResult('error', '二号失败'), TODAY, account='ab12cd34')
    raw = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert 'wps' in raw[TODAY] and 'wps#ab12cd34' in raw[TODAY]   # main 用原键
    assert st.get('wps', TODAY)['state'] == 'ok'
    assert st.get('wps', TODAY, account='ab12cd34')['state'] == 'error'
    assert st.done_today('wps') is True       # done_today 默认看 main


def test_recs_lists_all_accounts(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', '主'), TODAY)
    st.mark('wps', CheckinResult('ok', '二'), TODAY, account='x2')
    recs = st.recs('wps', TODAY)
    assert set(recs) == {'main', 'x2'}
    assert recs['x2']['message'] == '二'


def test_set_balance_and_expiring_per_account(tmp_path):
    st = DailyState(tmp_path)
    st.mark('wps', CheckinResult('ok', 'm'), TODAY)
    st.mark('wps', CheckinResult('ok', 'm2'), TODAY, account='x2')
    st.set_balance('wps', TODAY, '999', account='x2')
    st.set_expiring('wps', TODAY, '50 · 10-01到期', account='x2')
    assert st.get('wps', TODAY, account='x2')['balance'] == '999'
    assert st.get('wps', TODAY, account='x2')['expiring'] == '50 · 10-01到期'
    assert not st.get('wps', TODAY).get('balance')


def test_streak_per_account(tmp_path):
    st = DailyState(tmp_path)
    y = (dt.date.fromisoformat(TODAY) - dt.timedelta(days=1)).isoformat()
    st.mark('wps', CheckinResult('ok', 'm'), y)
    st.mark('wps', CheckinResult('ok', 'm'), TODAY)
    st.mark('wps', CheckinResult('ok', 'm2'), TODAY, account='x2')
    assert st.streak('wps', TODAY) == 2
    assert st.streak('wps', TODAY, account='x2') == 1
