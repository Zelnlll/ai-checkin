from app.config import Config
from app.credentials import CredentialStore
from app.platforms.base import CheckinResult
from app.state import DailyState
from app.webapp import collect_status, render_html

PLATFORMS = ['wps', 'dazi', 'minimax', 'qoder', 'modelscope']


def _setup(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, set(PLATFORMS))
    store.save('wps', {'cookie': 'wps_sid=x'})
    state = DailyState(tmp_path)
    state.mark('wps', CheckinResult('ok', '成功', '+100', balance='2592', streak=3),
               state_today())
    state.mark('dazi', CheckinResult('already', '已签到', '+500'), state_today())
    return cfg, store, state


def state_today():
    import datetime as dt
    return dt.date.today().isoformat()


def test_collect_status_fields(tmp_path):
    cfg, store, state = _setup(tmp_path)
    status = collect_status(cfg, store, state, PLATFORMS)
    assert status['today'] == state_today()
    assert status['done'] == 2 and status['total'] == 5
    wps = next(p for p in status['platforms'] if p['platform'] == 'wps')
    assert wps['title'] == 'WPS 灵犀' and wps['state'] == 'ok'
    assert wps['balance'] == '2592' and wps['streak'] == 3
    qoder = next(p for p in status['platforms'] if p['platform'] == 'qoder')
    assert qoder['credential'] == '未导入凭证' and qoder['state'] == ''


def test_error_card_shows_reason(tmp_path):
    cfg, store, state = _setup(tmp_path)
    state.mark('qoder', CheckinResult('error', '870 真拒签'), state_today())
    html = render_html(collect_status(cfg, store, state, PLATFORMS))
    assert '870 真拒签' in html and '失败' in html


def test_render_html_dashboard(tmp_path):
    cfg, store, state = _setup(tmp_path)
    html = render_html(collect_status(cfg, store, state, PLATFORMS))
    assert '签到中心' in html
    assert '已签 2 / 5' in html
    assert 'WPS 灵犀' in html and '2592' in html
    assert 'class="icon"' in html        # 每平台图标色块
    assert '未导入凭证' in html             # qoder 卡片状态
    assert '上次执行' not in html           # 已并入上次签到一条
    assert '上次签到' in html and '今天 ' in html


def test_render_html_has_detail_modal(tmp_path):
    cfg, store, state = _setup(tmp_path)
    html = render_html(collect_status(cfg, store, state, PLATFORMS))
    assert 'id="mask"' in html and 'showDetail(' in html
    assert 'closeDetail' in html


def test_card_shows_earliest_expiring(tmp_path):
    cfg, store, state = _setup(tmp_path)
    state.set_expiring('wps', state_today(), '1500 · 10-15到期')
    status = collect_status(cfg, store, state, PLATFORMS)
    wps = next(p for p in status['platforms'] if p['platform'] == 'wps')
    assert wps['expiring'] == '1500 · 10-15到期'
    html = render_html(status)
    assert '最快到期' in html and '1500 · 10-15到期' in html
