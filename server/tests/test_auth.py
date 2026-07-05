"""Tests for auth routes and authenticated media serving (M1 task 1.2).

No DB rows are created; providers are faked in-memory.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.providers import registry
from app.providers.base import MediaStore

USERNAME = "analyst"
PASSWORD = "correct-horse-battery"

TEST_CONFIG = {
    "TESTING": True,
    "SESSION_COOKIE_SECURE": False,
    "RATELIMIT_ENABLED": False,
}

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakepngbytes"


class FakeMediaStore(MediaStore):
    """In-memory MediaStore double keyed by relative path."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files

    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        self.files[suggested_name] = file_bytes
        return suggested_name

    def open(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def exists(self, relative_path: str) -> bool:
        return relative_path in self.files


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ANALYST_USERNAME", USERNAME)
    monkeypatch.setenv("ANALYST_PASSWORD", PASSWORD)
    app = create_app(TEST_CONFIG)
    with app.test_client() as test_client:
        yield test_client


def log_in(client):
    return client.post(
        "/api/login", json={"username": USERNAME, "password": PASSWORD}
    )


# --- /api/login -----------------------------------------------------------


def test_login_success_returns_204(client):
    resp = log_in(client)
    assert resp.status_code == 204
    assert resp.data == b""


def test_login_wrong_password_returns_401(client):
    resp = client.post(
        "/api/login", json={"username": USERNAME, "password": "wrong"}
    )
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_login_missing_fields_returns_401(client):
    resp = client.post("/api/login", json={})
    assert resp.status_code == 401
    assert "error" in resp.get_json()


# --- /api/me and /api/logout -----------------------------------------------


def test_me_reflects_session_state(client):
    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": False}

    assert log_in(client).status_code == 204

    resp = client.get("/api/me")
    assert resp.status_code == 200
    assert resp.get_json() == {"authenticated": True}

    resp = client.post("/api/logout")
    assert resp.status_code == 204

    resp = client.get("/api/me")
    assert resp.get_json() == {"authenticated": False}


# --- /media/<path> ---------------------------------------------------------


def test_media_requires_session(client):
    resp = client.get("/media/x.png")
    assert resp.status_code == 401
    assert "error" in resp.get_json()


def test_media_serves_bytes_with_mimetype(client, monkeypatch):
    fake_store = FakeMediaStore({"x.png": PNG_BYTES})
    monkeypatch.setattr(registry, "get_media_store", lambda: fake_store)

    assert log_in(client).status_code == 204
    resp = client.get("/media/x.png")
    assert resp.status_code == 200
    assert resp.data == PNG_BYTES
    assert resp.mimetype == "image/png"


def test_media_missing_file_returns_404(client, monkeypatch):
    fake_store = FakeMediaStore({})
    monkeypatch.setattr(registry, "get_media_store", lambda: fake_store)

    assert log_in(client).status_code == 204
    resp = client.get("/media/missing.png")
    assert resp.status_code == 404
    assert "error" in resp.get_json()
