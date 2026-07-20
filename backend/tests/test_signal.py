"""Backend tests for Straddle Compass signal endpoints."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
API = f"{BASE_URL.rstrip('/')}/api"

ADMIN_EMAIL = "sapphirealphacapital@gmail.com"
ADMIN_PASSWORD = "Vcxgfdtre@!0"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


REQUIRED_FIELDS = ["bias", "spot", "atm", "up_strike", "up_trend",
                   "down_strike", "down_trend", "note", "box_size",
                   "reversal", "updated_label"]


class TestSignalPublic:
    def test_get_signal_public_returns_shape(self):
        r = requests.get(f"{API}/terminal/signal")
        assert r.status_code == 200
        data = r.json()
        for f in REQUIRED_FIELDS:
            assert f in data, f"missing field {f}"
        assert "_id" not in data


class TestSignalAuth:
    def test_put_requires_auth(self):
        r = requests.put(f"{API}/terminal/signal", json={"bias": "Bullish"})
        assert r.status_code == 401

    def test_put_invalid_token(self):
        r = requests.put(f"{API}/terminal/signal",
                         headers={"Authorization": "Bearer notavalidtoken"},
                         json={"bias": "Bullish"})
        assert r.status_code == 401


class TestSignalAutoDerive:
    def test_neutral_with_bullish_legs_derives_bullish(self, auth_headers):
        # up_trend Bearish + down_trend Bullish => Bullish (falling ATM+200)
        payload = {
            "bias": "Neutral",
            "spot": "24,000", "atm": "24000",
            "up_strike": "24200", "up_trend": "Bearish",
            "down_strike": "23800", "down_trend": "Bullish",
            "note": "test-derive-bull",
        }
        r = requests.put(f"{API}/terminal/signal", headers=auth_headers, json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["bias"] == "Bullish"
        # Persisted
        g = requests.get(f"{API}/terminal/signal").json()
        assert g["bias"] == "Bullish"
        assert g["up_strike"] == "24200"
        assert g["down_strike"] == "23800"

    def test_neutral_with_bearish_legs_derives_bearish(self, auth_headers):
        payload = {
            "bias": "Neutral",
            "spot": "24,000", "atm": "24000",
            "up_strike": "24200", "up_trend": "Bullish",
            "down_strike": "23800", "down_trend": "Bearish",
            "note": "test-derive-bear",
        }
        r = requests.put(f"{API}/terminal/signal", headers=auth_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["bias"] == "Bearish"

    def test_neutral_neutral_stays_neutral(self, auth_headers):
        payload = {
            "bias": "Neutral",
            "spot": "24,000", "atm": "24000",
            "up_strike": "24200", "up_trend": "Neutral",
            "down_strike": "23800", "down_trend": "Neutral",
            "note": "test-neutral",
        }
        r = requests.put(f"{API}/terminal/signal", headers=auth_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["bias"] == "Neutral"

    def test_explicit_bias_not_overridden(self, auth_headers):
        # Explicit Bullish must remain Bullish even if legs disagree
        payload = {
            "bias": "Bullish",
            "spot": "24,000", "atm": "24000",
            "up_strike": "24200", "up_trend": "Bullish",  # would derive Bearish
            "down_strike": "23800", "down_trend": "Bearish",
            "note": "explicit-bull",
        }
        r = requests.put(f"{API}/terminal/signal", headers=auth_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["bias"] == "Bullish"


def test_restore_bullish_demo_state(token):
    """FINAL: restore to Bullish demo state per test spec."""
    payload = {
        "bias": "Neutral",  # auto-derive to Bullish
        "spot": "24,000", "atm": "24000",
        "up_strike": "24200", "up_trend": "Bearish",
        "down_strike": "23800", "down_trend": "Bullish",
        "note": "ATM+200 falling, ATM-200 rising — bullish setup.",
    }
    r = requests.put(f"{API}/terminal/signal",
                     headers={"Authorization": f"Bearer {token}"}, json=payload)
    assert r.status_code == 200
    assert r.json()["bias"] == "Bullish"
    g = requests.get(f"{API}/terminal/signal").json()
    assert g["bias"] == "Bullish"
    assert g["spot"] == "24,000"
