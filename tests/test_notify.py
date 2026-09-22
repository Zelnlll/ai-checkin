import pytest

from app.notify import WeComNotifier, build_card
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
    ADAPTERS['wps'] = _Wps()
    ADAPTERS['qoder'] = _Qoder()
    yield
    del ADAPTERS['wps'], ADAPTERS['qoder']


def test_all_success_card_title_and_rows(adapters_registered):
    card = build_card([
        CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分')),
        CheckinOutcome('qoder', CheckinResult('already', '今日活动已领取')),
    ], '2026-09-22')
    tc = card['template_card']
    assert tc['card_type'] == 'text_notice'
    assert tc['main_title']['title'] == '每日签到 · 全部成功'
    assert tc['sub_title_text'] == '2026-09-22'
    rows = {r['keyname']: r['value'] for r in tc['horizontal_content_list']}
    assert rows['WPS 灵犀'].startswith('✅') and '+100' in rows['WPS 灵犀']
    assert rows['Qoder'].startswith('✔')


def test_failure_marks_card(adapters_registered):
    card = build_card([
        CheckinOutcome('qoder', CheckinResult('error', 'HTTP 401 token 失效')),
    ], '2026-09-22')
    tc = card['template_card']
    assert '有失败' in tc['main_title']['title']
    assert tc['emphasis_indicator'] == 1
    row = tc['horizontal_content_list'][0]
    assert '❌' in row['value'] and '401' in row['value']


def test_push_posts_wrapped_payload(adapters_registered):
    sent = []

    def fake_post(method, url, headers, body=None, **kw):
        sent.append((method, url, body))
        return {'errcode': 0, 'errmsg': 'ok'}

    n = WeComNotifier('https://qyapi.weixin.qq.com/robot/send?key=x', post=fake_post)
    ok = n.push([CheckinOutcome('wps', CheckinResult('ok', '成功'))], '2026-09-22')
    assert ok is True
    method, url, body = sent[0]
    assert method == 'POST' and 'qyapi.weixin.qq.com' in url
    assert body['msgtype'] == 'template_card'


def test_push_swallows_webhook_errors():
    def boom(*a, **k):
        raise RuntimeError('网络不通')

    n = WeComNotifier('https://qyapi.weixin.qq.com/x', post=boom)
    assert n.push([], '2026-09-22') is False


def test_push_returns_false_on_errcode():
    n = WeComNotifier('https://x', post=lambda *a, **k: {'errcode': 93000, 'errmsg': 'invalid'})
    assert n.push([], '2026-09-22') is False


def test_empty_webhook_skips_push():
    n = WeComNotifier('', post=lambda *a, **k: {'errcode': 0})
    assert n.push([], '2026-09-22') is False
