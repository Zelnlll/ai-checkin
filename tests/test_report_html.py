from app.platforms.base import CheckinResult
from app.report_html import build_report_html
from app.scheduler import CheckinOutcome


def _html(outcomes=None, today='2026-09-22'):
    if outcomes is None:
        outcomes = [
            CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分')),
            CheckinOutcome('qoder', CheckinResult('already', '今日活动已领取', '+100 Credits')),
        ]
    return build_report_html(outcomes, today)


def test_has_dashboard_header_and_progress():
    h = _html()
    assert '签到中心' in h
    assert '已签 2 / 2' in h
    assert '2026-09-22' in h


def test_each_platform_gets_a_card():
    h = _html()
    assert 'WPS 灵犀' in h
    assert 'Qoder' in h
    assert '+100 积分' in h
    assert '+100 Credits' in h


def test_status_pill_text():
    h = _html()
    assert '今天已签到' in h          # ok
    assert '已签到' in h              # already 也有标识


def test_failure_card_marked_red():
    h = _html([CheckinOutcome('dazi', CheckinResult('error', 'Cookie 失效'))])
    assert '已签 0 / 1' in h
    assert '失败' in h
    assert 'Cookie 失效' in h
    assert 'status-error' in h


def test_progress_bar_width_reflects_ratio():
    h = _html([
        CheckinOutcome('wps', CheckinResult('ok', 'x', '+1')),
        CheckinOutcome('qoder', CheckinResult('error', 'y')),
    ])
    assert 'width:50%' in h
