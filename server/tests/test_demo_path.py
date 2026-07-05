"""M8 task 8.1: demo-path end-to-end test.

ONE integrated test walks the full demo path through the Flask test client:
login -> capture (one PNG) -> eager 4-step pipeline -> triage annotation ->
Library search -> citation-enforced report claim -> deliverable export HTML
-> PDF smoke. All AI providers are faked (deterministic outputs, zero cost);
Celery runs eagerly in-process.

Qdrant note: vectors.upsert_post is wrapped, not replaced — it records the
call AND writes the real point to the live compose Qdrant, so GET /api/search
exercises the genuine query path (the query embedding is stubbed to the same
deterministic vector, cosine ~1.0). Teardown removes the Qdrant point and
every DB row (reports first: citations RESTRICT posts).

The capture->processed wall clock is printed and asserted < 30s as an
informational proxy for the live demo target (run with -s to see it).
"""

from __future__ import annotations

import io
import time
import types
import uuid

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from app import create_app, vectors
from app.db import get_engine
from app.models import Post, Report
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import (
    EmbeddingProvider,
    Entity,
    ExtractionProvider,
    MediaStore,
    OCRProvider,
    TranslationProvider,
)

DEMO_ZH = "安热沙金瓶防晒霜实测：军训暴晒一周完全没黑，敏感肌也不刺激。"
DEMO_EN = (
    "Anessa gold-bottle sunscreen field test: a full week of outdoor drills "
    "with zero tanning, and no irritation on sensitive skin."
)
DEMO_ENTITY = Entity(
    text_zh="安热沙", text_en="Anessa", type="brand", confidence=0.97
)
# Deterministic, non-degenerate 1536-dim vector (repeating 1/13..13/13 ramp).
DEMO_VECTOR = [((i % 13) + 1) / 13.0 for i in range(1536)]

CLAIM_TEXT = (
    "Anessa dominates sunscreen conversation among Chinese student "
    "communities during summer training season."
)


class _FakeOCR(OCRProvider):
    def ocr_image(self, image_bytes: bytes, mime_type: str) -> str:
        return DEMO_ZH


class _FakeTranslation(TranslationProvider):
    def translate(self, zh_text, glossary):
        return DEMO_EN


class _FakeExtraction(ExtractionProvider):
    def extract(self, zh_text, en_text):
        return [DEMO_ENTITY]


class _FakeEmbedding(EmbeddingProvider):
    @property
    def dimension(self) -> int:
        return 1536

    def embed(self, text: str) -> list[float]:
        return list(DEMO_VECTOR)


class _FakeMediaStore(MediaStore):
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        self.files[suggested_name] = file_bytes
        return suggested_name

    def open(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def exists(self, relative_path: str) -> bool:
        return relative_path in self.files

    def delete(self, relative_path: str) -> None:
        self.files.pop(relative_path, None)


def _tiny_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def demo(monkeypatch):
    """Fully wired demo environment: fakes, eager Celery, app client, cleanup.

    vectors.upsert_post is wrapped (record + REAL live-Qdrant write) so the
    search step runs against genuine vector retrieval.
    """
    monkeypatch.setenv("ANALYST_USERNAME", "analyst")
    monkeypatch.setenv("ANALYST_PASSWORD", "test-password")

    # Single shared instances: the media store must keep its saved files
    # across registry lookups (capture saves, the OCR task re-opens).
    ocr, translator = _FakeOCR(), _FakeTranslation()
    extractor, embedder, store = _FakeExtraction(), _FakeEmbedding(), _FakeMediaStore()
    monkeypatch.setattr(registry, "get_ocr_provider", lambda: ocr)
    monkeypatch.setattr(registry, "get_translation_provider", lambda: translator)
    monkeypatch.setattr(registry, "get_extraction_provider", lambda: extractor)
    monkeypatch.setattr(registry, "get_embedding_provider", lambda: embedder)
    monkeypatch.setattr(registry, "get_media_store", lambda: store)

    upserts: list[tuple[str, list[float]]] = []
    real_upsert = vectors.upsert_post

    def recording_upsert(post_id: str, vector: list[float]) -> None:
        upserts.append((post_id, list(vector)))
        real_upsert(post_id, vector)  # live Qdrant point for the search step

    monkeypatch.setattr(vectors, "upsert_post", recording_upsert)

    previous = (celery.conf.task_always_eager, celery.conf.task_eager_propagates)
    celery.conf.update(task_always_eager=True, task_eager_propagates=True)

    app = create_app(
        {"TESTING": True, "SESSION_COOKIE_SECURE": False, "RATELIMIT_ENABLED": False}
    )
    created = {"reports": [], "posts": []}
    yield types.SimpleNamespace(
        client=app.test_client(), upserts=upserts, created=created
    )

    celery.conf.task_always_eager, celery.conf.task_eager_propagates = previous
    with Session(get_engine()) as session:  # reports first: RESTRICT on posts
        for report_id in created["reports"]:
            session.query(Report).filter(
                Report.id == uuid.UUID(report_id)
            ).delete(synchronize_session=False)
        session.commit()
    for post_id in created["posts"]:
        vectors.delete_post(post_id)
    with Session(get_engine()) as session:
        for post_id in created["posts"]:
            post = session.get(Post, uuid.UUID(post_id))
            if post is not None:
                session.delete(post)
        session.commit()


def test_demo_path_end_to_end(demo):
    client = demo.client

    # 1. Login with the monkeypatched analyst credentials.
    response = client.post(
        "/api/login", json={"username": "analyst", "password": "test-password"}
    )
    assert 200 <= response.status_code < 300

    # 2+3. Capture one PNG; eager Celery runs the whole chain inline.
    started = time.perf_counter()
    response = client.post(
        "/api/capture",
        data={
            "images": (io.BytesIO(_tiny_png()), "demo-sunscreen.png"),
            "caption": "夏日防晒实测",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202, response.get_json()
    post_id = response.get_json()["post_id"]
    demo.created["posts"].append(post_id)

    body = client.get(f"/api/posts/{post_id}").get_json()
    elapsed = time.perf_counter() - started
    print(
        f"\n[demo-path] capture -> fully processed in {elapsed:.2f}s "
        "(live target: <= 30s)"
    )
    assert elapsed < 30.0

    for step in ("ocr", "translate", "extract", "embed"):
        assert body[f"{step}_status"] == "success", body
    assert body["full_ocr_text"] == DEMO_ZH
    assert body["machine_translation"] == DEMO_EN
    assert body["entities"] == [DEMO_ENTITY.__dict__]
    # Wrapper recorded the upsert AND wrote the live Qdrant point.
    assert demo.upserts == [(post_id, DEMO_VECTOR)]

    # 4. Triage: annotate skincare / zhongcao (种草).
    response = client.put(
        f"/api/posts/{post_id}/annotation",
        json={"category": "skincare", "consumer_signal": "zhongcao"},
    )
    assert response.status_code == 200
    annotation = response.get_json()
    assert annotation["category"] == "skincare"
    assert annotation["consumer_signal"] == "zhongcao"

    # 5. Library: live-Qdrant search; the stubbed query embedding equals the
    # stored vector, so the post must come back (cosine ~1.0).
    response = client.get("/api/search?q=what is XHS saying about sunscreen")
    assert response.status_code == 200
    results = response.get_json()["results"]
    hits = [item for item in results if item["id"] == post_id]
    assert len(hits) == 1, [item["id"] for item in results]
    assert hits[0]["has_annotation"] is True
    assert hits[0]["annotation"]["category"] == "skincare"

    # 6. Report: create + one brand_watch claim citing the captured post.
    response = client.post("/api/reports", json={"title": "Demo Path Weekly Report"})
    assert response.status_code == 201
    report_id = response.get_json()["id"]
    demo.created["reports"].append(report_id)

    response = client.post(
        f"/api/reports/{report_id}/blocks",
        json={
            "section": "brand_watch",
            "block_type": "claim",
            "text_content": CLAIM_TEXT,
            "citations": [post_id],
        },
    )
    assert response.status_code == 201, response.get_json()
    assert [c["post_id"] for c in response.get_json()["citations"]] == [post_id]

    # 7a. Export HTML (deliverable): claim + citation marker + zh appendix.
    response = client.get(f"/api/reports/{report_id}/export?variant=deliverable")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    html = response.get_data(as_text=True)
    assert CLAIM_TEXT in html
    assert '<sup class="cite">' in html  # citation marker on the claim
    assert 'href="#src-1"' in html and 'id="src-1"' in html  # marker -> appendix
    assert DEMO_ZH in html  # appendix preserves the source Chinese snippet

    # 7b. PDF smoke (chromium ships in the api image; skip only if truly absent).
    response = client.get(f"/api/reports/{report_id}/export.pdf")
    if response.status_code == 503:
        pytest.skip(
            "chromium unavailable in test container: "
            + response.get_json()["error"]
        )
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")
