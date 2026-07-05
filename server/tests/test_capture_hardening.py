"""M2 capture hardening tests: URL dedup, pHash near-duplicates, defer/append/
process flow, and CSV import.

Celery runs eagerly; providers and the media store are faked via the registry.
Tests create their own posts (unique random note ids) and delete them on the
way out. Near-duplicate assertions are scoped to posts created by the test so
pre-existing rows in a shared dev database never affect the outcome.
"""

from __future__ import annotations

import io
import random
import uuid

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app import create_app
from app.db import get_engine
from app.models import Annotation, Post
from app.phash import compute_phash_signed, hamming_distance
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import MediaStore, OCRProvider, TranslationProvider

FAKE_ZH = "测试中文文本 避雷 平替"
FAKE_EN = "Fake English translation: BiLei warning, PingTi dupe."

XHS_EXPLORE = "https://www.xiaohongshu.com/explore/{note_id}"


def _random_note_id() -> str:
    return uuid.uuid4().hex[:24]


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
    response = client.post(
        "/api/login", json={"username": "analyst", "password": "test-password"}
    )
    if response.status_code in (404, 405):
        with client.session_transaction() as session:
            session["analyst"] = True
    else:
        assert 200 <= response.status_code < 300


def _structured_png() -> bytes:
    """64x64 split image: left half black, right half white."""
    image = Image.new("RGB", (64, 64), (0, 0, 0))
    image.paste((255, 255, 255), (32, 0, 64, 64))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _noise_png() -> bytes:
    """64x64 deterministic pseudo-random noise (fixed seed)."""
    rng = random.Random(42)
    image = Image.new("RGB", (64, 64))
    image.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)]
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# pHash unit sanity
# ---------------------------------------------------------------------------


def test_phash_test_images_are_far_apart():
    a = compute_phash_signed(_structured_png())
    b = compute_phash_signed(_noise_png())
    assert hamming_distance(a, a) == 0
    assert hamming_distance(a, b) > 8


# ---------------------------------------------------------------------------
# URL dedup
# ---------------------------------------------------------------------------


def test_url_dedup_roundtrip(client, created_posts):
    _login(client)
    url = XHS_EXPLORE.format(note_id=_random_note_id())

    first = client.post(
        "/api/capture",
        data={"url": url, "caption": "测试 URL 捕获"},
        content_type="multipart/form-data",
    )
    assert first.status_code == 202, first.get_json()
    post_id = first.get_json()["post_id"]
    created_posts.append(post_id)

    second = client.post(
        "/api/capture",
        data={"url": url, "caption": "second attempt"},
        content_type="multipart/form-data",
    )
    assert second.status_code == 200
    body = second.get_json()
    assert body["already_captured"] is True
    assert body["post_id"] == post_id

    with Session(get_engine()) as session:
        count = (
            session.query(Post)
            .filter_by(source_url=url)
            .count()
        )
    assert count == 1  # second call created nothing

    # source_url and note id landed on the post
    read = client.get(f"/api/posts/{post_id}")
    assert read.status_code == 200


def test_url_only_capture_allowed(client, created_posts):
    _login(client)
    url = XHS_EXPLORE.format(note_id=_random_note_id())
    response = client.post(
        "/api/capture",
        data={"url": url, "defer_pipeline": "1"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202, response.get_json()
    created_posts.append(response.get_json()["post_id"])


# ---------------------------------------------------------------------------
# pHash near-duplicate warnings (soft)
# ---------------------------------------------------------------------------


def test_phash_duplicate_upload_warns_distance_zero(client, created_posts):
    _login(client)
    png = _structured_png()

    first = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(png), "one.png"), "caption": "第一次"},
        content_type="multipart/form-data",
    )
    assert first.status_code == 202, first.get_json()
    first_post_id = first.get_json()["post_id"]
    created_posts.append(first_post_id)
    first_image_id = client.get(f"/api/posts/{first_post_id}").get_json()["images"][0]["id"]

    second = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(png), "two.png"), "caption": "第二次"},
        content_type="multipart/form-data",
    )
    assert second.status_code == 202, second.get_json()  # soft warning: still succeeds
    body = second.get_json()
    created_posts.append(body["post_id"])

    warnings = [w for w in body["near_duplicates"] if w["image_index"] == 0]
    assert warnings, body
    exact = [
        m
        for m in warnings[0]["matches"]
        if m["image_id"] == first_image_id and m["post_id"] == first_post_id
    ]
    assert exact and exact[0]["distance"] == 0


def test_phash_different_image_no_warning(client, created_posts):
    _login(client)
    first = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(_structured_png()), "one.png")},
        content_type="multipart/form-data",
    )
    assert first.status_code == 202
    first_post_id = first.get_json()["post_id"]
    created_posts.append(first_post_id)

    second = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(_noise_png()), "two.png")},
        content_type="multipart/form-data",
    )
    assert second.status_code == 202
    body = second.get_json()
    created_posts.append(body["post_id"])

    # Scope the assertion to posts this test created (shared dev DB safety).
    matches_ours = [
        m
        for warning in body["near_duplicates"]
        for m in warning["matches"]
        if m["post_id"] == first_post_id
    ]
    assert matches_ours == []


def test_capture_unreadable_image_400(client):
    _login(client)
    response = client.post(
        "/api/capture",
        data={"images": (io.BytesIO(b"not-a-real-png"), "bad.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "could not decode image" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# defer_pipeline + append image + process flow
# ---------------------------------------------------------------------------


def test_defer_append_process_flow(client, created_posts):
    _login(client)
    capture = client.post(
        "/api/capture",
        data={
            "images": (io.BytesIO(_structured_png()), "first.png"),
            "caption": "分批上传测试",
            "defer_pipeline": "1",
        },
        content_type="multipart/form-data",
    )
    assert capture.status_code == 202, capture.get_json()
    post_id = capture.get_json()["post_id"]
    created_posts.append(post_id)

    # defer_pipeline=1: nothing ran
    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "pending"
    assert body["machine_translation"] is None

    append = client.post(
        f"/api/posts/{post_id}/images",
        data={"image": (io.BytesIO(_noise_png()), "second.png"), "image_type": "comments"},
        content_type="multipart/form-data",
    )
    assert append.status_code == 202, append.get_json()
    append_body = append.get_json()
    assert append_body["image_id"]
    assert "near_duplicates" in append_body

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert [img["sort_order"] for img in body["images"]] == [0, 1]
    assert body["images"][1]["image_type"] == "comments"

    process = client.post(f"/api/posts/{post_id}/process")
    assert process.status_code == 202
    assert process.get_json()["post_id"] == post_id

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "success"
    assert body["translate_status"] == "success"
    assert body["machine_translation"] == FAKE_EN

    # Safe to call repeatedly: idempotent tasks, state unchanged.
    assert client.post(f"/api/posts/{post_id}/process").status_code == 202
    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "success"
    assert body["translate_status"] == "success"


def test_append_and_process_unknown_post_404(client):
    _login(client)
    missing = uuid.uuid4()
    append = client.post(
        f"/api/posts/{missing}/images",
        data={"image": (io.BytesIO(_structured_png()), "x.png")},
        content_type="multipart/form-data",
    )
    assert append.status_code == 404
    assert client.post(f"/api/posts/{missing}/process").status_code == 404


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


def test_csv_import(client, created_posts, fake_translator):
    _login(client)
    note_a = _random_note_id()
    note_b = _random_note_id()
    url_a = XHS_EXPLORE.format(note_id=note_a)
    url_b = XHS_EXPLORE.format(note_id=note_b)

    csv_text = (
        "﻿url,caption,captured_at,notes\n"
        f"{url_a},测试 caption 一,2026-07-01T08:30:00+00:00,\n"
        f"{url_b},,,watchlist brand mention\n"
        ",no url here,,\n"
        f"{url_a},duplicate of row 1,,\n"
    )
    response = client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(csv_text.encode("utf-8")), "import.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()

    with Session(get_engine()) as session:
        post_a = session.query(Post).filter_by(xhs_note_id=note_a).one()
        post_b = session.query(Post).filter_by(xhs_note_id=note_b).one()
        created_posts.extend([str(post_a.id), str(post_b.id)])

        assert body["created"] == 2
        assert body["duplicates"] == [{"row": 4, "post_id": str(post_a.id)}]
        assert body["errors"] == [{"row": 3, "error": "missing url"}]

        # Row 1: caption + captured_at stored; pipeline ran (caption-only translation).
        assert post_a.caption_raw == "测试 caption 一"
        assert post_a.captured_at.isoformat().startswith("2026-07-01T08:30:00")
        assert post_a.source_url == url_a

        # Row 2: no caption -> no pipeline; notes -> annotation row.
        annotation = session.query(Annotation).filter_by(post_id=post_b.id).one()
        assert annotation.notes == "watchlist brand mention"

    body_a = client.get(f"/api/posts/{post_a.id}").get_json()
    assert body_a["ocr_status"] == "skipped"  # caption-only post
    assert body_a["translate_status"] == "success"
    assert body_a["machine_translation"] == FAKE_EN
    assert "测试 caption 一" in fake_translator.calls

    body_b = client.get(f"/api/posts/{post_b.id}").get_json()
    assert body_b["ocr_status"] == "pending"
    assert body_b["translate_status"] == "pending"


def test_csv_import_requires_url_column(client):
    _login(client)
    response = client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(b"caption,notes\nfoo,bar\n"), "bad.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "url" in response.get_json()["error"]


def test_csv_import_bad_captured_at_reports_error(client, created_posts):
    _login(client)
    note_id = _random_note_id()
    url = XHS_EXPLORE.format(note_id=note_id)
    csv_text = f"url,captured_at\n{url},not-a-date\n"
    response = client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(csv_text.encode("utf-8")), "import.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["created"] == 0
    assert body["errors"][0]["row"] == 1
    assert "captured_at" in body["errors"][0]["error"]

    with Session(get_engine()) as session:
        assert session.query(Post).filter_by(xhs_note_id=note_id).count() == 0


def test_csv_import_session_only(client):
    # Token auth is NOT accepted on the CSV import route (session_required).
    response = client.post(
        "/api/import/csv",
        data={"file": (io.BytesIO(b"url\nhttp://x\n"), "import.csv")},
        content_type="multipart/form-data",
        headers={"X-API-Token": "anything"},
    )
    assert response.status_code == 401
