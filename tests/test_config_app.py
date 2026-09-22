from app.config import load_config


def test_wecom_app_fields_parsed():
    cfg = load_config({'WECOM_CORP_ID': 'ww123', 'WECOM_CORP_SECRET': 'sec',
                       'WECOM_AGENT_ID': '1000002', 'WECOM_TO_USER': 'zhangsan'})
    assert cfg.wecom_corp_id == 'ww123'
    assert cfg.wecom_corp_secret == 'sec'
    assert cfg.wecom_agent_id == 1000002
    assert cfg.wecom_to_user == 'zhangsan'
    assert cfg.wecom_chat_id == ''


def test_defaults_empty_when_not_configured():
    cfg = load_config({})
    assert cfg.wecom_corp_id == '' and cfg.wecom_agent_id == 0


def test_wecom_api_base_parsed():
    cfg = load_config({'WECOM_API_BASE': 'http://1.2.3.4:52000'})
    assert cfg.wecom_api_base == 'http://1.2.3.4:52000'


def test_wecom_api_base_default_official():
    cfg = load_config({})
    assert cfg.wecom_api_base == 'https://qyapi.weixin.qq.com/cgi-bin'
