"""Backend tests for Sapphire Alpha Capital API (waitlist + contact)."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # Fallback to reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def unique_email():
    return f"test_{uuid.uuid4().hex[:10]}@example.com"


# --- Root ---
def test_root():
    r = requests.get(f"{API}/")
    assert r.status_code == 200
    assert "message" in r.json()


# --- Waitlist ---
class TestWaitlist:
    def test_count_returns_int(self):
        r = requests.get(f"{API}/waitlist/count")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_signup_new_email(self, unique_email):
        # count before
        c_before = requests.get(f"{API}/waitlist/count").json()["count"]

        r = requests.post(f"{API}/waitlist", json={"email": unique_email, "name": "Test User"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["email"] == unique_email
        assert "id" in data
        assert "created_at" in data

        # count after
        c_after = requests.get(f"{API}/waitlist/count").json()["count"]
        assert c_after == c_before + 1

    def test_duplicate_email_returns_409(self, unique_email):
        # unique_email already inserted in previous test
        r = requests.post(f"{API}/waitlist", json={"email": unique_email})
        assert r.status_code == 409
        assert "waitlist" in r.json()["detail"].lower()

    def test_invalid_email_returns_422(self):
        r = requests.post(f"{API}/waitlist", json={"email": "not-an-email"})
        assert r.status_code == 422


# --- Contact ---
class TestContact:
    def test_contact_valid(self):
        email = f"contact_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "name": "Jane Doe",
            "email": email,
            "message": "Hello, I'm interested in Sapphire Alpha.",
            "company": "Acme Corp",
        }
        r = requests.post(f"{API}/contact", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["email"] == payload["email"]
        assert data["message"] == payload["message"]
        assert data["company"] == payload["company"]
        assert "id" in data
        assert "created_at" in data

    def test_contact_invalid_email(self):
        r = requests.post(
            f"{API}/contact",
            json={"name": "X", "email": "bad-email", "message": "hi"},
        )
        assert r.status_code == 422

    def test_contact_missing_fields(self):
        r = requests.post(f"{API}/contact", json={"email": "a@b.com"})
        assert r.status_code == 422
