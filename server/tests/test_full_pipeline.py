"""M3 full-pipeline tests: 4-step chain, idempotency, retry cascades,
corrections -> re-embed, failure taxonomy, and the Inbox listing.

All providers are faked via the registry (late binding); Celery runs eagerly.
Qdrant note: app.vectors.upsert_post is monkeypatched to record calls instead
of hitting Qdrant, EXCEPT test_vectors_roundtrip_against_live_qdrant, which
exercises app/vectors.py against the live compose Qdrant and deletes its
point (by point id) on the way out. Tests delete their DB rows afterwards.
"""

from __future__ import annotations

import datetime
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app import create_app, vectors
from app.db import get_engine
from app.models import Annotation, Post
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import (
    EmbeddingProvider,
    Entity,
    ExtractionProvider,
    MediaStore,
    OCRProvider,
    TransientProviderError,
    TranslationProvider,
)

FAKE_ZH = "测试中文文本 避雷 平替"
FAKE_EN = "Fake English translation: BiLei warning, PingTi dupe."
FAKE_ENTITIES = [
    Entity(text_zh="花西子", text_en="Florasis", type="brand", confidence=0.95),
    Entity(text_zh="烟酰胺", text_en="niacinamide", type="ingredient", confidence=0.8),
]
FAKE_VECTOR = [0.001] * 1536


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeOCRProvider(OCRProvider):
    def __init__(self):
        self.calls = 0

    def ocr_image(self, image_bytes: bytes, mime_type: str) -> str:
        self.calls += 1
        return FAKE_ZH


class FakeTranslationProvider(TranslationProvider):
    def __init__(self):
        self.calls: list[str] = []

    def translate(self, zh_text, glossary):
        self.calls.append(zh_text)
        return FAKE_EN


class FakeExtractionProvider(ExtractionProvider):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.exc: Exception | None = None

    def extract(self, zh_text, en_text):
        self.calls.append((zh_text, en_text))
        if self.exc is not None:
            raise self.exc
        return list(FAKE_ENTITIES)


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.calls: list[str] = []

    @property
    def dimension(self) -> int:
        return 1536

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(FAKE_VECTOR)


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


class Fakes:
    def __init__(self):
        self.ocr = FakeOCRProvider()
        self.translator = FakeTranslationProvider()
        self.extractor = FakeExtractionProvider()
        self.embedder = FakeEmbeddingProvider()
        self.store = FakeMediaStore()
        self.upserts: list[tuple[str, list[float]]] = []

    def counts(self) -> tuple[int, int, int, int, int]:
        return (
            self.ocr.calls,
            len(self.translator.calls),
            len(self.extractor.calls),
            len(self.embedder.calls),
            len(self.upserts),
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fakes(monkeypatch):
    fakes = Fakes()
    monkeypatch.setattr(registry, "get_ocr_provider", lambda: fakes.ocr)
    monkeypatch.setattr(registry, "get_translation_provider", lambda: fakes.translator)
    monkeypatch.setattr(registry, "get_extraction_provider", lambda: fakes.extractor)
    monkeypatch.setattr(registry, "get_embedding_provider", lambda: fakes.embedder)
    monkeypatch.setattr(registry, "get_media_store", lambda: fakes.store)
    monkeypatch.setattr(
        vectors, "upsert_post",
        lambda post_id, vector: fakes.upserts.append((post_id, vector)),
    )
    return fakes


@pytest.fixture()
def eager_celery():
    previous = (celery.conf.task_always_eager, celery.conf.task_eager_propagates)
    celery.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield celery
    celery.conf.task_always_eager, celery.conf.task_eager_propagates = previous


@pytest.fixture()
def app(monkeypatch, fakes, eager_celery):
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
    assert 200 <= response.status_code < 300


def _tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _capture(client, caption=None, with_image=True, defer=False) -> str:
    data = {}
    if with_image:
        data["images"] = (io.BytesIO(_tiny_png()), "shot.png")
    if caption is not None:
        data["caption"] = caption
    if defer:
        data["defer_pipeline"] = "1"
    response = client.post("/api/capture", data=data, content_type="multipart/form-data")
    assert response.status_code == 202, response.get_json()
    return response.get_json()["post_id"]


# ---------------------------------------------------------------------------
# Full chain
# ---------------------------------------------------------------------------


def test_full_chain_end_to_end(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "success"
    assert body["translate_status"] == "success"
    assert body["extract_status"] == "success"
    assert body["embed_status"] == "success"
    assert body["entities"] == [entity.__dict__ for entity in FAKE_ENTITIES]
    assert body["machine_translation"] == FAKE_EN
    assert body["final_translation"] is None  # analyst field untouched

    # Extraction saw both sides; embed document is the pinned bilingual concat.
    zh_side, en_side = fakes.extractor.calls[-1]
    assert "测试 caption" in zh_side and FAKE_ZH in zh_side
    assert en_side == FAKE_EN
    assert fakes.embedder.calls[-1] == zh_side + "\n---\n" + FAKE_EN

    # Qdrant upsert recorded with the post's own id and a 1536-dim vector.
    assert len(fakes.upserts) == 1
    upsert_id, vector = fakes.upserts[0]
    assert upsert_id == post_id
    assert len(vector) == 1536

    with Session(get_engine()) as session:
        post = session.get(Post, uuid.UUID(post_id))
        assert post.embedded_at is not None


def test_process_reenqueue_skips_completed_steps(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    counts_after_first_run = fakes.counts()

    response = client.post(f"/api/posts/{post_id}/process")
    assert response.status_code == 202

    # force=False + all steps already success: no provider is called again.
    assert fakes.counts() == counts_after_first_run


# ---------------------------------------------------------------------------
# Retry cascade
# ---------------------------------------------------------------------------


def test_retry_translate_forces_downstream_but_not_ocr(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    ocr0, tr0, ex0, em0, up0 = fakes.counts()

    response = client.post(f"/api/posts/{post_id}/retry/translate")
    assert response.status_code == 202
    assert response.get_json() == {
        "post_id": post_id,
        "steps": ["translate", "extract", "embed"],
    }

    assert fakes.counts() == (ocr0, tr0 + 1, ex0 + 1, em0 + 1, up0 + 1)
    # Re-embedding replaced the point under the same id (upsert idempotency).
    assert fakes.upserts[-1][0] == post_id


def test_retry_unknown_step_400_and_unknown_post_404(client, fakes):
    _login(client)
    response = client.post(f"/api/posts/{uuid.uuid4()}/retry/transmogrify")
    assert response.status_code == 400
    response = client.post(f"/api/posts/{uuid.uuid4()}/retry/embed")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Corrections -> re-embed (iron law #2)
# ---------------------------------------------------------------------------


def test_patch_corrected_text_triggers_forced_reembed(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    _, _, _, embeds0, upserts0 = fakes.counts()

    response = client.patch(
        f"/api/posts/{post_id}", json={"corrected_text": "更正后的中文文本"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["corrected_text"] == "更正后的中文文本"
    assert body["full_ocr_text"] == FAKE_ZH  # machine output untouched

    # Forced embed ran despite embed_status already 'success'.
    assert len(fakes.embedder.calls) == embeds0 + 1
    assert "更正后的中文文本" in fakes.embedder.calls[-1]
    assert FAKE_ZH not in fakes.embedder.calls[-1]  # corrected_text wins
    assert len(fakes.upserts) == upserts0 + 1
    assert fakes.upserts[-1][0] == post_id


def test_patch_entities_alone_does_not_reembed(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    counts_before = fakes.counts()

    edited = [
        {"text_zh": "珂拉琪", "text_en": "Colorkey", "type": "brand", "confidence": 1.0}
    ]
    response = client.patch(f"/api/posts/{post_id}", json={"entities": edited})
    assert response.status_code == 200
    assert response.get_json()["entities"] == edited
    assert fakes.counts() == counts_before  # no re-embed, no provider calls


@pytest.mark.parametrize(
    "bad_entities",
    [
        {"text_zh": "x"},  # object, not array
        [{"text_zh": "x"}],  # missing keys
        ["just a string"],  # item not an object
        [{"text_zh": "x", "text_en": "y", "type": "brand", "confidence": "high"}],
    ],
)
def test_patch_invalid_entities_returns_400(client, created_posts, fakes, bad_entities):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    counts_before = fakes.counts()

    response = client.patch(f"/api/posts/{post_id}", json={"entities": bad_entities})
    assert response.status_code == 400
    assert fakes.counts() == counts_before


def test_patch_image_corrected_ocr_no_reembed(client, created_posts, fakes):
    _login(client)
    post_id = _capture(client, caption="测试 caption")
    created_posts.append(post_id)
    counts_before = fakes.counts()

    image_id = client.get(f"/api/posts/{post_id}").get_json()["images"][0]["id"]
    response = client.patch(
        f"/api/posts/{post_id}/images/{image_id}",
        json={"corrected_ocr": "更正后的单图 OCR"},
    )
    assert response.status_code == 200
    assert response.get_json() == {"image_id": image_id}
    assert fakes.counts() == counts_before  # no re-aggregate, no re-embed

    response = client.patch(
        f"/api/posts/{post_id}/images/{uuid.uuid4()}",
        json={"corrected_ocr": "x"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------


def test_transient_extract_failure_exhausts_retries_and_stops_chain(
    client, created_posts, fakes, eager_celery
):
    _login(client)
    post_id = _capture(client, caption="测试 caption", defer=True)
    created_posts.append(post_id)

    fakes.extractor.exc = TransientProviderError("rate limited by provider")

    from app.pipeline.tasks import build_chain

    # eager_propagates must be off for Celery's eager retry loop to engage
    # (Task.apply re-applies a Retry only when it is returned, not raised).
    # The exhausted failure still surfaces when the chain feeds the next hop.
    eager_celery.conf.task_eager_propagates = False
    with pytest.raises(TransientProviderError):
        build_chain(post_id).apply_async()

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["ocr_status"] == "success"
    assert body["translate_status"] == "success"
    assert body["extract_status"] == "failed"
    assert body["extract_error_type"] == "transient"
    assert "rate limited" in body["extract_error_message"]
    assert body["embed_status"] == "pending"  # chain stopped before embed

    assert len(fakes.extractor.calls) == 3  # first attempt + 2 retries
    assert fakes.embedder.calls == []
    assert fakes.upserts == []


# ---------------------------------------------------------------------------
# Inbox listing
# ---------------------------------------------------------------------------


def test_list_posts_shape_ordering_and_annotation_flag(client, created_posts, fakes):
    _login(client)
    older_id = _capture(client, caption="旧" * 200)
    newer_id = _capture(client, caption="新帖 caption", with_image=False)
    created_posts.extend([older_id, newer_id])

    utc = datetime.timezone.utc
    with Session(get_engine()) as session:
        session.get(Post, uuid.UUID(older_id)).captured_at = datetime.datetime(
            2026, 1, 1, tzinfo=utc
        )
        session.get(Post, uuid.UUID(newer_id)).captured_at = datetime.datetime(
            2026, 1, 2, tzinfo=utc
        )
        session.add(Annotation(post_id=uuid.UUID(newer_id), notes="watchlist brand"))
        session.commit()

    body = client.get("/api/posts?limit=200").get_json()
    assert body["total"] >= 2
    listed = {item["id"]: item for item in body["posts"]}
    assert {older_id, newer_id} <= set(listed)

    order = [item["id"] for item in body["posts"]]
    assert order.index(newer_id) < order.index(older_id)  # captured_at DESC

    older = listed[older_id]
    assert len(older["caption_raw"]) == 120  # truncated preview
    assert older["image_count"] == 1
    assert older["first_image_url"].startswith("/media/")
    assert older["has_annotation"] is False
    assert older["xhs_note_id"] is None
    for step in ("ocr", "translate", "extract", "embed"):
        assert older[f"{step}_status"] == "success"
        assert older[f"{step}_error_type"] is None
        assert older[f"{step}_error_message"] is None

    newer = listed[newer_id]
    assert newer["image_count"] == 0
    assert newer["first_image_url"] is None
    assert newer["has_annotation"] is True
    assert newer["ocr_status"] == "skipped"  # caption-only post

    page = client.get("/api/posts?limit=1&offset=0").get_json()
    assert len(page["posts"]) == 1
    assert page["total"] == body["total"]


def test_list_posts_requires_session(client):
    assert client.get("/api/posts").status_code == 401


# ---------------------------------------------------------------------------
# Live Qdrant round-trip for app/vectors.py (cleans up its point by id)
# ---------------------------------------------------------------------------


def test_vectors_roundtrip_against_live_qdrant():
    point_id = str(uuid.uuid4())
    try:
        vectors.ensure_collection()  # idempotent second call
        vectors.upsert_post(point_id, [0.5] * 1536)
        vectors.upsert_post(point_id, [0.25] * 1536)  # replace, not duplicate
        points = vectors.get_client().retrieve(
            collection_name=vectors.COLLECTION_NAME, ids=[point_id]
        )
        assert len(points) == 1
        assert points[0].payload == {"post_id": point_id}
    finally:
        vectors.delete_post(point_id)
    assert (
        vectors.get_client().retrieve(
            collection_name=vectors.COLLECTION_NAME, ids=[point_id]
        )
        == []
    )
