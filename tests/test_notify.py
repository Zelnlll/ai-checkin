import pytest

from app.notify import WeComNotifier
from app.platforms import ADAPTERS
from app.platforms.base import Adapter, CheckinResult
from app.scheduler import CheckinOutcome


class _Wps(Adapter):
    platform = 'wps'
    title = 'WPS 灵犀'
    credential_kind = 'cookie'

    def checkin(self, creds):
        return CheckinResult('ok', 'x')


class _Qoder(Adapter):
    platform = 'qoder'
    title = 'Qoder'
    credential_kind = 'token'

    def checkin(self, creds):
        return CheckinResult('ok', 'x')


@pytest.fixture
def adapters_registered():
    saved = {k: ADAPTERS.get(k) for k in ('wps', 'qoder')}
    ADAPTERS['wps'] = _Wps()
    ADAPTERS['qoder'] = _Qoder()
    yield
    for k, v in saved.items():
        if v is not None:
            ADAPTERS[k] = v
        else:
            ADAPTERS.pop(k, None)


def test_build_text_plain_lines(adapters_registered):
    from app.notify import build_text
    msg = build_text([
        CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分')),
        CheckinOutcome('qoder', CheckinResult('error', 'HTTP 401 token 失效')),
    ], '2026-09-22')
    assert msg['msgtype'] == 'text'
    c = msg['text']['content']
    assert '每日签到 2026-09-22' in c
    assert '🟢 WPS 灵犀 +100 积分' in c
    assert '🔴 Qoder HTTP 401 token 失效' in c
    assert '<' not in c          # 纯文本无任何标签


def test_push_swallows_webhook_errors():
    def boom(*a, **k):
        raise RuntimeError('网络不通')

    n = WeComNotifier('https://x', post=boom)
    assert n.push([], '2026-09-22') is False


def test_empty_webhook_skips_push():
    n = WeComNotifier('', post=lambda *a, **k: {'errcode': 0})
    assert n.push([], '2026-09-22') is False


def test_textcard_big_title_and_small_rows(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分')),
        CheckinOutcome('qoder', CheckinResult('already', '今日活动已领取', '+100 Credits')),
    ], '2026-09-22')
    assert msg['msgtype'] == 'textcard'
    tc = msg['textcard']
    assert tc['title'] == '签到成功 2/2'
    assert tc['url'].startswith('http')
    assert '2026-09-22' in tc['description']
    assert '🟢 WPS 灵犀 +100 积分' in tc['description']  # wps=绿
    assert '<' not in tc['description']   # 微信插件不解析 HTML，必须纯文本


def test_textcard_failure_title_red_mark(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('wps', CheckinResult('error', 'Cookie 失效，请重新导入')),
    ], '2026-09-22')
    tc = msg['textcard']
    assert '有失败 0/1' in tc['title']
    assert '🔴 WPS 灵犀 Cookie 失效' in tc['description']  # 失败覆盖为红
    assert '<' not in tc['description']


def test_textcard_description_under_512_bytes(adapters_registered):
    from app.notify import build_textcard
    long_msg = '失' * 200
    msg = build_textcard([
        CheckinOutcome(p, CheckinResult('error', long_msg))
        for p in ('wps', 'qoder', 'dazi', 'minimax', 'modelscope')
    ], '2026-09-22')
    assert len(msg['textcard']['description'].encode('utf-8')) <= 512


def test_textcard_per_platform_dots(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('dazi', CheckinResult('ok', '签到成功', '+500 积分')),
        CheckinOutcome('minimax', CheckinResult('already', '已签到', '+400 积分')),
        CheckinOutcome('qoder', CheckinResult('ok', '成功', '+100 Credits')),
    ], '2026-09-22')
    d = msg['textcard']['description']
    assert '🔵 百度搭子' in d
    assert '🟣 MiniMax Code' in d
    assert '⚫ Qoder' in d


def test_textcard_line_shows_balance_and_streak(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('wps', CheckinResult('ok', '成功', '+100 积分',
                                            balance='2592', streak=3)),
    ], '2026-09-22')
    d = msg['textcard']['description']
    assert '🟢 WPS 灵犀 +100｜余2592｜连3天' in d


def test_textcard_omits_absent_extras(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('wps', CheckinResult('ok', '成功', '+100 积分', streak=1)),
    ], '2026-09-22')
    d = msg['textcard']['description']
    assert '余' not in d and '连' not in d


def test_textcard_busy_line_shows_reason_not_signed(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('modelscope', CheckinResult('busy', '今日未发放，稍后再查')),
    ], '2026-09-22')
    d = msg['textcard']['description']
    assert '今日未发放' in d and '已签到' not in d


def test_textcard_lines_fit_one_row(adapters_registered):
    from app.notify import build_textcard
    msg = build_textcard([
        CheckinOutcome('minimax', CheckinResult('ok', '成功', '+400 积分',
                                                balance='2262', streak=4)),
        CheckinOutcome('qoder', CheckinResult('ok', '成功', '+100 Credits')),
    ], '2026-09-22')
    d = msg['textcard']['description']
    assert '🟣 MiniMax +400｜余2262｜连4天' in d   # 短名+去"积分"
    assert '⚫ Qoder +100Cr' in d                  # Credits→Cr
    for line in d.split(chr(10)):
        assert len(line) <= 26                     # 手机单行预算
