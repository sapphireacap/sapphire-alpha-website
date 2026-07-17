"""Backend tests for Auth + Alpha Terminal endpoints."""
import os
import uuid
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
    data = r.json()
    assert "access_token" in data
    return data["access_token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_login_success(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        data = r.json()
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == ADMIN_EMAIL
        assert isinstance(data["access_token"], str) and len(data["access_token"]) > 20

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrongpass!!"})
        assert r.status_code == 401

    def test_me_requires_token(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, auth_headers):
        r = requests.get(f"{API}/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL


class TestScannersPublic:
    def test_scanners_list(self):
        r = requests.get(f"{API}/terminal/scanners")
        assert r.status_code == 200
        data = r.json()
        assert data["updated_label"] == "Today, 09:30 AM IST"
        keys = [s["key"] for s in data["scanners"]]
        assert keys == ["momentum", "relative_strength", "breakout", "positional"]
        # Momentum should have >=3 (seeded)
        mom = next(s for s in data["scanners"] if s["key"] == "momentum")
        assert mom["count"] >= 3

    def test_stocks_momentum_seeded(self):
        r = requests.get(f"{API}/terminal/stocks", params={"scanner": "momentum"})
        assert r.status_code == 200
        rows = r.json()
        tickers = [x["ticker"] for x in rows]
        for t in ["NVDA", "CRWD", "PLTR"]:
            assert t in tickers
        # Sorted by order asc
        orders = [x["order"] for x in rows]
        assert orders == sorted(orders)
        # No _id leaked
        for row in rows:
            assert "_id" not in row

    def test_stocks_unknown_scanner(self):
        r = requests.get(f"{API}/terminal/stocks", params={"scanner": "bogus"})
        assert r.status_code == 400


class TestAdminCRUDAuthRequired:
    def test_create_requires_auth(self):
        r = requests.post(f"{API}/terminal/stocks", json={"ticker": "X"})
        assert r.status_code == 401

    def test_update_requires_auth(self):
        r = requests.put(f"{API}/terminal/stocks/anyid", json={"ticker": "X"})
        assert r.status_code == 401

    def test_delete_requires_auth(self):
        r = requests.delete(f"{API}/terminal/stocks/anyid")
        assert r.status_code == 401

    def test_reorder_requires_auth(self):
        r = requests.put(f"{API}/terminal/stocks/reorder/apply", json={"scanner": "momentum", "ordered_ids": []})
        assert r.status_code == 401


class TestAdminCRUDFlow:
    def test_full_crud_and_reorder(self, auth_headers):
        ticker = f"TEST{uuid.uuid4().hex[:4].upper()}"
        # Create
        r = requests.post(f"{API}/terminal/stocks", headers=auth_headers, json={
            "scanner": "momentum", "ticker": ticker, "company": "Test Co",
            "momentum_score": "50.0", "volume": "1x avg", "bias": "Neutral",
        })
        assert r.status_code == 200, r.text
        created = r.json()
        sid = created["id"]
        assert created["ticker"] == ticker

        # Verify via GET
        rows = requests.get(f"{API}/terminal/stocks", params={"scanner": "momentum"}).json()
        assert any(x["id"] == sid and x["ticker"] == ticker for x in rows)

        # Update
        r = requests.put(f"{API}/terminal/stocks/{sid}", headers=auth_headers, json={
            "scanner": "momentum", "ticker": ticker, "company": "Test Co Updated",
            "momentum_score": "55.0", "volume": "2x avg", "bias": "Bullish",
        })
        assert r.status_code == 200
        assert r.json()["company"] == "Test Co Updated"
        assert r.json()["bias"] == "Bullish"

        # Reorder: put created stock first
        rows = requests.get(f"{API}/terminal/stocks", params={"scanner": "momentum"}).json()
        ids = [x["id"] for x in rows]
        # Move sid to front
        ids.remove(sid)
        new_order = [sid] + ids
        r = requests.put(f"{API}/terminal/stocks/reorder/apply", headers=auth_headers,
                         json={"scanner": "momentum", "ordered_ids": new_order})
        assert r.status_code == 200
        rows2 = requests.get(f"{API}/terminal/stocks", params={"scanner": "momentum"}).json()
        assert rows2[0]["id"] == sid

        # Restore order (put created stock last before delete)
        restore_order = ids + [sid]
        requests.put(f"{API}/terminal/stocks/reorder/apply", headers=auth_headers,
                     json={"scanner": "momentum", "ordered_ids": restore_order})

        # Delete
        r = requests.delete(f"{API}/terminal/stocks/{sid}", headers=auth_headers)
        assert r.status_code == 200
        # Confirm gone
        rows3 = requests.get(f"{API}/terminal/stocks", params={"scanner": "momentum"}).json()
        assert not any(x["id"] == sid for x in rows3)

        # Delete again -> 404
        r = requests.delete(f"{API}/terminal/stocks/{sid}", headers=auth_headers)
        assert r.status_code == 404
