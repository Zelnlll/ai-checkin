from app.config import Config
from app.credentials import CredentialStore
from app.platforms.base import CheckinResult
from app.state import DailyState
from app.webapp import collect_status, render_html, render_settings

PLATFORMS = ['wps', 'dazi', 'minimax', 'qoder', 'modelscope']


def _setup(tmp_path):
    cfg = Config((10, 5), 3, '', tmp_path)
    store = CredentialStore(tmp_path, set(PLATFORMS))
    store.save('wps', {'cookie': 'wps_sid=x'})
    store.save('dazi', {'cookie': 'bce-user-info=x'})
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


def _setup_two_accounts(tmp_path):
    import datetime as dt
    today = dt.date.today().isoformat()
    cfg, store, state = _setup(tmp_path)
    store.upsert('wps', {'cookie': 'wps_sid=y', 'label': '小号'})
    second = store.load_all('wps')[1]['id']
    state.mark('wps', CheckinResult('ok', '主成', '+100 积分', balance='500'), today)
    state.mark('wps', CheckinResult('ok', '二成', '+100 积分', balance='500'),
               today, account=second)
    state.set_expiring('wps', today, '50 · 10-01到期', account=second)
    state.set_expiring('wps', today, '80 · 11-20到期')
    return cfg, store, state, today


def test_collect_status_aggregates_accounts(tmp_path):
    cfg, store, state, today = _setup_two_accounts(tmp_path)
    status = collect_status(cfg, store, state, PLATFORMS)
    wps = next(p for p in status['platforms'] if p['platform'] == 'wps')
    assert wps['state'] == 'ok'
    assert wps['reward'] == '+200 积分' and wps['balance'] == '1000'
    assert wps['expiring'] == '50 · 10-01到期'      # 跨账号取最早
    assert len(wps['accounts']) == 2
    assert {a['label'] for a in wps['accounts']} == {'主账号', '小号'}
    assert '2 账号' in wps['account_note']


def test_card_pill_shows_account_count(tmp_path):
    cfg, store, state, today = _setup_two_accounts(tmp_path)
    html = render_html(collect_status(cfg, store, state, PLATFORMS))
    assert '今天已签到 ✅·2号' in html


def test_single_account_unchanged(tmp_path):
    cfg, store, state = _setup(tmp_path)
    status = collect_status(cfg, store, state, PLATFORMS)
    wps = next(p for p in status['platforms'] if p['platform'] == 'wps')
    assert wps['reward'] == '+100' and wps['account_note'] == ''
    assert len(wps['accounts']) == 1


def test_settings_escapes_hostile_label(tmp_path):
    cfg, store, state = _setup(tmp_path)
    store.upsert('wps', {'cookie': 'b', 'label': 'x"onmouseover="alert(1)'})
    status = collect_status(cfg, store, state, PLATFORMS)
    html = render_settings(status)
    # 引号被清洗 → 无法提前闭合属性形成注入；纯文字残留无害
    assert 'x"on' not in html and 'onmouseover="' not in html


def test_ghost_record_of_removed_account_ignored(tmp_path):
    import datetime as dt
    cfg, store, state = _setup(tmp_path)
    # 先以"未导入凭证"落 main 错误记录，再导入哈希 id 账号 → 卡片不应钉死失败
    state.mark('qoder', CheckinResult('error', '未导入凭证（Qoder）'),
               dt.date.today().isoformat())
    store2 = CredentialStore(tmp_path, set(PLATFORMS))
    store2.upsert('qoder', {'token': 'dt-new'})
    status = collect_status(cfg, store2, state, PLATFORMS)
    qoder = next(p for p in status['platforms'] if p['platform'] == 'qoder')
    assert qoder['state'] == ''


def test_dashboard_gear_entry(tmp_path):
    cfg, store, state = _setup(tmp_path)
    html = render_html(collect_status(cfg, store, state, PLATFORMS))
    assert 'href="/settings"' in html and '⚙' in html
    assert '设置' not in html.split("slogan")[1][:80]   # 旧文字链接已移除


def test_settings_account_rows_have_update_and_meta(tmp_path):
    cfg, store, state, today = _setup_two_accounts(tmp_path)
    html = render_settings(collect_status(cfg, store, state, PLATFORMS))
    assert '更新凭证' in html
    assert 'toggleEdit(' in html and 'display:none' in html   # 表单默认收起
