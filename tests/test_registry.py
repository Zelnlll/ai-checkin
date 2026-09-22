import pytest

from app.platforms.base import Adapter, CheckinResult


def test_result_done_states():
    assert CheckinResult('ok', 'x').done()
    assert CheckinResult('already', 'x').done()
    assert not CheckinResult('busy', 'x').done()
    assert not CheckinResult('error', 'x').done()


def test_result_rejects_unknown_state():
    with pytest.raises(ValueError):
        CheckinResult('maybe', 'x')


def test_get_adapter_unknown_platform_raises():
    from app.platforms import get_adapter
    with pytest.raises(KeyError):
        get_adapter('nonexistent')


def test_registered_adapter_is_retrievable():
    from app.platforms import ADAPTERS, get_adapter

    class Dummy(Adapter):
        platform = 'dummy'
        title = 'Dummy'
        credential_kind = 'token'

        def checkin(self, creds):
            return CheckinResult('ok', 'noop')

    ADAPTERS['dummy'] = Dummy()
    try:
        assert get_adapter('dummy') is ADAPTERS['dummy']
    finally:
        del ADAPTERS['dummy']


def test_default_token_status_unknown():
    class Bare(Adapter):
        platform = 'bare'
        title = 'Bare'
        credential_kind = 'token'

        def checkin(self, creds):
            return CheckinResult('ok', 'noop')

    assert Bare().token_status({}) == {
        'known': False, 'expired': False, 'expires_at': '', 'days_left': None}
