"""The vendor pause switch: while VENDOR_APIS_PAUSED is on (the default), nothing may
send a request to Definedge or Dhan, and each chokepoint must fail with its OWN
existing error type so callers' current handling applies. No network is used: the
HTTP clients and websockets are replaced by tripwires that fail the test if touched."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dhan_auth  # noqa: E402
import dhan_health  # noqa: E402
import dhan_master  # noqa: E402
import vendor_pause  # noqa: E402
from definedge_service import DefinedgeError, DefinedgeService  # noqa: E402


class _Tripwire:
    def __init__(self, *a, **k):
        raise AssertionError("a network client was created while vendor requests are paused")


class _FakeColl:
    async def find_one(self, *a, **k):
        # A perfectly good cached Dhan token / Definedge session: pause must still refuse.
        return {"id": "current", "access_token": "x" * 40, "expires_at": "2099-01-01T00:00:00+00:00",
                "api_session_key": "sess", "uid": "u", "actid": "a", "susertoken": "t"}


class _FakeDb:
    def __getattr__(self, name):
        return _FakeColl()

    def __getitem__(self, name):
        return _FakeColl()


@pytest.fixture
def paused(monkeypatch):
    monkeypatch.delenv("VENDOR_APIS_PAUSED", raising=False)       # the default IS paused
    monkeypatch.delenv("DHAN_DISABLED", raising=False)
    monkeypatch.setenv("DHAN_CLIENT_ID", "1")
    monkeypatch.setenv("DHAN_PIN", "123456")
    monkeypatch.setenv("DHAN_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    for mod in ("definedge_service", "dhan_auth", "dhan_master"):
        monkeypatch.setattr(sys.modules[mod].httpx, "AsyncClient", _Tripwire)
    return monkeypatch


def run(coro):
    return asyncio.run(coro)


def test_default_is_paused_and_zero_resumes(monkeypatch):
    monkeypatch.delenv("VENDOR_APIS_PAUSED", raising=False)
    assert vendor_pause.paused() is True
    for off in ("0", "false", "NO", "off", " 0 "):
        monkeypatch.setenv("VENDOR_APIS_PAUSED", off)
        assert vendor_pause.paused() is False, off
    monkeypatch.setenv("VENDOR_APIS_PAUSED", "1")
    assert vendor_pause.paused() is True


def test_definedge_every_entry_point_refuses_without_touching_the_network(paused):
    d = DefinedgeService(_FakeDb(), "token", "secret")
    for call in (d.trigger_otp, d._session_key, d._get_all_master):
        with pytest.raises(DefinedgeError, match="paused"):
            run(call())
    with pytest.raises(DefinedgeError, match="paused"):
        run(d.verify_otp("123456", "otp-token"))
    assert run(d.ws_credentials()) is None                          # the websocket stays idle


def test_dhan_token_is_refused_even_when_a_valid_cached_token_exists(paused):
    with pytest.raises(dhan_auth.DhanAuthError, match="paused"):
        run(dhan_auth.get_access_token(_FakeDb()))
    with pytest.raises(dhan_auth.DhanAuthError, match="paused"):
        run(dhan_auth.get_access_token(_FakeDb(), force=True))
    with pytest.raises(dhan_auth.DhanAuthError, match="paused"):
        run(dhan_auth.login())


def test_dhan_health_reports_unavailable_so_streams_and_charts_skip_it(paused):
    dhan_health._down_until = 0.0
    assert dhan_health.available() is False


def test_dhan_master_download_is_refused(paused):
    with pytest.raises(dhan_master.DhanMasterError, match="paused"):
        run(dhan_master._load("NSE"))


def test_when_resumed_the_chokepoints_are_open_again(monkeypatch):
    monkeypatch.setenv("VENDOR_APIS_PAUSED", "0")
    monkeypatch.delenv("DHAN_DISABLED", raising=False)
    dhan_health._down_until = 0.0
    assert dhan_health.available() is True
    d = DefinedgeService(_FakeDb(), "token", "secret")
    assert run(d._session_key()) == "sess"                          # no pause error: normal behaviour
    assert run(dhan_auth.get_access_token(_FakeDb())) == "x" * 40


def test_streams_idle_instead_of_connecting_while_paused(monkeypatch):
    import definedge_stream
    monkeypatch.delenv("VENDOR_APIS_PAUSED", raising=False)
    monkeypatch.setattr(definedge_stream.websockets, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket opened")))
    monkeypatch.setattr(definedge_stream, "NO_CREDENTIALS_RETRY_SECONDS", 0.01)

    async def go():
        s = definedge_stream.DefinedgeStream(DefinedgeService(_FakeDb(), "t", "s"))
        s.start()
        await asyncio.sleep(0.1)
        await s.stop()

    run(go())
