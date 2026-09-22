import pytest

from app.config import load_config


def test_defaults_when_env_empty():
    cfg = load_config({})
    assert cfg.checkin_time == (10, 5)
    assert cfg.retry_times == 3
    assert cfg.wecom_webhook == ''


def test_checkin_time_parsed_from_env():
    cfg = load_config({'CHECKIN_TIME': '08:30'})
    assert cfg.checkin_time == (8, 30)


def test_bad_checkin_time_falls_back_to_default():
    cfg = load_config({'CHECKIN_TIME': '25:99'})
    assert cfg.checkin_time == (10, 5)


def test_retry_times_parsed_from_env():
    cfg = load_config({'RETRY_TIMES': '5'})
    assert cfg.retry_times == 5


def test_negative_retry_times_rejected():
    with pytest.raises(ValueError):
        load_config({'RETRY_TIMES': '-1'})


def test_non_numeric_retry_times_rejected():
    with pytest.raises(ValueError):
        load_config({'RETRY_TIMES': 'abc'})
