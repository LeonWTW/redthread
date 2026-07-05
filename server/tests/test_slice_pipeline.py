"""End-to-end tests for the M1 vertical slice: capture -> OCR -> translate -> read.

Celery runs eagerly; providers and the media store are faked via the registry
(late binding). Tests create their own posts and delete them on the way out.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app import create_app
from app.db import get_engine
from app.models import Post
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import MediaStore, OCRProvider, TranslationProvider

FAKE_ZH = "测试中文文本 避雷 平替"
FAKE_EN = "Fake English translation: BiLei warning, PingTi dupe."


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeOCRProvider(OCRProvider):
    def ocr_image(self, image_bytes: bytes, mime_type: str) -> str:
        return FAKE_ZH


class FakeTranslationProvider(TranslationProvider):
    def __init__(self):
        self.calls: list[str] = []

    def translate(self, zh_text, glossary):
        self.calls.append(zh_text)
        return FAKE_EN


class FakeMediaStore(MediaStore):
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        self.files[suggested_name] = file_bytes
        return suggested_name

    def open(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def exists(self, relative_path: str) -> bool:
        return relative_path in self.files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_translator(monkeypatch):
    translator = FakeTranslationProvider()
    monkeypatch.setattr(registry, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(registry, "get_translation_provider", lambda: translator)
    store = FakeMediaStore()
    monkeypatch.setattr(registry, "get_media_store", lambda: store)
    return translator


@pytest.fixture()
def eager_celery():
    previous = (celery.conf.task_always_eager, celery.conf.task_eager_propagates)
    celery.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield celery
    celery.conf.task_always_eager, celery.conf.task_eager_propagates = previous


@pytest.fixture()
def app(monkeypatch, fake_translator, eager_celery):
    monkeypatch.setenv("ANALYST_USERNAME", "analyst")
    monkeypatch.setenv("ANALYST_PASSWORD", "test-password")
    return create_app(
        {"TESTING": True, "SESSION_COOKIE_SECURE": False, "RATELIMIT_ENABLED": False}
    )


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def created_posts():
    """Collect post IDs created during a test and delete them afterwards."""
    ids: list[str] = []
    yield ids
    with Session(get_engine()) as session:
        for post_id in ids:
            post = session.get(Post, uuid.UUID(post_id))
            if post is not None:
                session.delete(post)
        session.commit()


def _login(client):
    """Authenticate the analyst session.

    Uses POST /api/login when available (task 1.2); falls back to writing the
    session directly if the endpoint is not implemented yet.
    """
    response = client.post(
        "/api/login", json={"username": "analyst", "password": "test-password"}
    )
    if response.status_code in (404, 405):
        with client.session_transaction() as session:
            session["analyst"] = True
    else:
        assert 200 <= response.status_code < 300


def _tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_capture_image_end_to_end(client, created_posts):
    _login(client)
    response = client.post(
        "/api/capture",
        data={
            "images": (io.BytesIO(_tiny_png()), "screenshot.png"),
            "caption": "测试 caption",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202, response.get_json()
    post_id = response.get_json()["post_id"]
    created_posts.append(post_id)

    read = client.get(f"/api/posts/{post_id}")
    assert read.status_code == 200
    body = read.get_json()
    assert body["id"] == post_id
    assert body["caption_raw"] == "测试 caption"
    assert body["full_ocr_text"] == FAKE_ZH
    assert body["machine_translation"] == FAKE_EN
    assert body["final_translation"] is None  # analyst field untouched
    assert body["ocr_status"] == "success"
    assert body["translate_status"] == "success"
    assert body["ocr_error_type"] is None
    assert len(body["images"]) == 1
    assert body["images"][0]["sort_order"] == 0
    assert body["images"][0]["image_type"] == "note_content"
    assert body["images"][0]["url"].startswith("/media/")


def test_heic_upload_rejected_with_415(client, created_posts):
    _login(client)
    response = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(b"fake-heic-bytes"), "photo.heic")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 415
    message = response.get_json()["error"]
    assert "PNG" in message and "JPEG" in message


def test_caption_only_capture_skips_ocr(client, created_posts, fake_translator):
    _login(client)
    response = client.post(
        "/api/capture",
        data={"caption": "只有 caption 没有图"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202, response.get_json()
    post_id = response.get_json()["post_id"]
    created_posts.append(post_id)

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "skipped"
    assert body["translate_status"] == "success"
    assert body["machine_translation"] == FAKE_EN
    assert body["images"] == []
    # Translation ran on the caption itself.
    assert fake_translator.calls[-1] == "只有 caption 没有图"


def test_capture_unauthenticated_returns_401(client):
    response = client.post(
        "/api/capture",
        data={"caption": "should not be captured"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_capture_with_api_token_header(client, created_posts, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "machine-token")
    response = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(_tiny_png()), "bot-shot.png")},
        content_type="multipart/form-data",
        headers={"X-API-Token": "machine-token"},
    )
    assert response.status_code == 202, response.get_json()
    created_posts.append(response.get_json()["post_id"])
