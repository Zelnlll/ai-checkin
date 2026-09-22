import pytest

from app.notify import WeComNotifier, build_markdown
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


def test_all_success_structure(adapters_registered):
    msg = build_markdown([
        CheckinOutcome('wps', CheckinResult('ok', '签到成功', '+100 积分')),
        CheckinOutcome('qoder', CheckinResult('already', '今日活动已领取', '+100 Credits')),
    ], '2026-09-22')
    assert msg['msgtype'] == 'markdown'
    c = msg['markdown']['content']
    assert c.startswith('# 📋 AI 平台签到')
    assert '2026-09-22' in c
    assert '全部成功 2/2' in c
    assert '战利品' in c and '+100 积分' in c and '+100 Credits' in c
    assert '✅ **WPS 灵犀**' in c
    assert '✔ **Qoder**' in c


def test_failure_shows_warning_color(adapters_registered):
    msg = build_markdown([
        CheckinOutcome('wps', CheckinResult('error', 'Cookie 失效，请重新导入')),
        CheckinOutcome('qoder', CheckinResult('ok', '成功', '+100 Credits')),
    ], '2026-09-22')
    c = msg['markdown']['content']
    assert '有失败 1/2' in c and '<font color="warning">' in c
    assert '❌ **Qoder**' not in c and '❌ **WPS 灵犀**' in c
    assert 'Cookie 失效' in c


def test_no_reward_line(adapters_registered):
    c = build_markdown([
        CheckinOutcome('wps', CheckinResult('already', '今日已签到')),
    ], '2026-09-22')['markdown']['content']
    assert '战利品' not in c


def test_push_posts_markdown_payload():
    sent = []

    def fake_post(method, url, headers, body=None, **kw):
        sent.append(body)
        return {'errcode': 0}

    n = WeComNotifier('https://x', post=fake_post)
    ok = n.push([CheckinOutcome('wps', CheckinResult('ok', '成功'))], '2026-09-22')
    assert ok is True
    assert sent[0]['msgtype'] == 'markdown'


def test_push_swallows_webhook_errors():
    def boom(*a, **k):
        raise RuntimeError('网络不通')

    n = WeComNotifier('https://x', post=boom)
    assert n.push([], '2026-09-22') is False


def test_empty_webhook_skips_push():
    n = WeComNotifier('', post=lambda *a, **k: {'errcode': 0})
    assert n.push([], '2026-09-22') is False
