"""M5 task 5.1 tests: GET /api/search and DELETE /api/posts/<id>.

Search runs against the LIVE compose Qdrant with deterministic fixed vectors
(no live OpenAI: the embedding provider is faked). Every test cleans up the
DB rows and Qdrant points it creates. The delete tests cover media-file and
vector cleanup plus the ON DELETE RESTRICT citation guard (409 with report
titles), which is a design decision, not an accident.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app import create_app, vectors
from app.db import get_engine
from app.models import Annotation, Post, PostImage, Report, ReportBlock, ReportCitation
from app.providers import registry
from app.providers.base import EmbeddingProvider, MediaStore, ProviderConfigError
from app.providers.media_local import LocalMediaStore

DIM = vectors.VECTOR_DIMENSION

# Deterministic fixed vectors: the query points almost exactly at post A,
# barely at post B, so the score order A > B is guaranteed under cosine.
VEC_A = [1.0] + [0.0] * (DIM - 1)
VEC_B = [0.0, 1.0] + [0.0] * (DIM - 2)
QUERY_VEC = [0.9, 0.1] + [0.0] * (DIM - 2)


class FakeQueryEmbedder(EmbeddingProvider):
    def __init__(self, vector: list[float]):
        self.vector = vector
        self.calls: list[str] = []

    @property
    def dimension(self) -> int:
        return DIM

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(self.vector)


class FakeMediaStore(MediaStore):
    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = dict(files or {})
        self.deleted: list[str] = []

    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        self.files[suggested_name] = file_bytes
        return suggested_name

    def open(self, relative_path: str) -> bytes:
        return self.files[relative_path]

    def exists(self, relative_path: str) -> bool:
        return relative_path in self.files

    def delete(self, relative_path: str) -> None:
        self.deleted.append(relative_path)
        self.files.pop(relative_path, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(monkeypatch):
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
    """Post IDs created during a test: DB rows AND Qdrant points are removed."""
    ids: list[str] = []
    yield ids
    for post_id in ids:
        vectors.delete_post(post_id)
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


def _make_post(caption: str, *, annotate: str | None = None,
               image_path: str | None = None) -> str:
    with Session(get_engine()) as session:
        post = Post(caption_raw=caption)
        session.add(post)
        session.flush()
        if annotate is not None:
            session.add(Annotation(post_id=post.id, notes=annotate,
                                   category="makeup"))
        if image_path is not None:
            session.add(PostImage(post_id=post.id, file_path=image_path))
        session.commit()
        return str(post.id)


# ---------------------------------------------------------------------------
# GET /api/search
# ---------------------------------------------------------------------------


def test_search_score_order_annotation_and_card_shape(
    client, created_posts, monkeypatch
):
    _login(client)
    post_a = _make_post("唇泥测试 lip mud", annotate="watchlist: Joocyee 酵色")
    post_b = _make_post("其他帖子 other post")
    created_posts.extend([post_a, post_b])
    vectors.upsert_post(post_a, VEC_A)
    vectors.upsert_post(post_b, VEC_B)

    embedder = FakeQueryEmbedder(QUERY_VEC)
    monkeypatch.setattr(registry, "get_embedding_provider", lambda: embedder)

    body = client.get("/api/search?q=lip mud&limit=50").get_json()
    assert body["query"] == "lip mud"
    assert embedder.calls == ["lip mud"]  # query embedded as-is

    ours = [item for item in body["results"] if item["id"] in (post_a, post_b)]
    assert [item["id"] for item in ours] == [post_a, post_b]  # score order
    assert ours[0]["score"] > ours[1]["score"]

    card_a, card_b = ours
    assert card_a["caption_raw"] == "唇泥测试 lip mud"  # source Chinese preserved
    assert card_a["has_annotation"] is True
    assert card_a["annotation"]["notes"] == "watchlist: Joocyee 酵色"
    assert card_a["annotation"]["category"] == "makeup"
    assert card_b["annotation"] is None
    for field in ("captured_at", "xhs_note_id", "image_count",
                  "first_image_url", "ocr_status", "embed_status"):
        assert field in card_a  # same card shape as the Inbox listing


def test_search_empty_or_missing_q_returns_400(client, monkeypatch):
    _login(client)
    embedder = FakeQueryEmbedder(QUERY_VEC)
    monkeypatch.setattr(registry, "get_embedding_provider", lambda: embedder)

    assert client.get("/api/search").status_code == 400
    assert client.get("/api/search?q=").status_code == 400
    assert client.get("/api/search?q=%20%20").status_code == 400
    assert embedder.calls == []  # rejected before any embedding cost


def test_search_unconfigured_provider_returns_503(client, monkeypatch):
    _login(client)

    def raise_config_error():
        raise ProviderConfigError("OPENAI_API_KEY is not set")

    monkeypatch.setattr(registry, "get_embedding_provider", raise_config_error)
    response = client.get("/api/search?q=lip mud")
    assert response.status_code == 503
    assert response.get_json() == {
        "error": "embedding provider not configured — check .env"
    }


def test_search_skips_qdrant_points_missing_in_postgres(
    client, created_posts, monkeypatch
):
    _login(client)
    ghost_id = str(uuid.uuid4())  # point exists in Qdrant, row never existed
    created_posts.append(ghost_id)
    vectors.upsert_post(ghost_id, VEC_A)

    monkeypatch.setattr(
        registry, "get_embedding_provider", lambda: FakeQueryEmbedder(QUERY_VEC)
    )
    body = client.get("/api/search?q=ghost&limit=50").get_json()
    assert ghost_id not in [item["id"] for item in body["results"]]


def test_search_requires_session(client):
    assert client.get("/api/search?q=lip mud").status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/posts/<id>
# ---------------------------------------------------------------------------


def test_delete_removes_row_media_and_qdrant_point(
    client, created_posts, monkeypatch
):
    _login(client)
    store = FakeMediaStore({"2026/07/test-delete.png": b"png-bytes"})
    monkeypatch.setattr(registry, "get_media_store", lambda: store)

    post_id = _make_post("待删除帖子", image_path="2026/07/test-delete.png")
    created_posts.append(post_id)
    vectors.upsert_post(post_id, VEC_A)

    response = client.delete(f"/api/posts/{post_id}")
    assert response.status_code == 204

    with Session(get_engine()) as session:
        assert session.get(Post, uuid.UUID(post_id)) is None
        images = session.query(PostImage).filter(
            PostImage.post_id == uuid.UUID(post_id)
        ).all()
        assert images == []  # cascade
    assert store.deleted == ["2026/07/test-delete.png"]
    assert not store.exists("2026/07/test-delete.png")
    assert (
        vectors.get_client().retrieve(
            collection_name=vectors.COLLECTION_NAME, ids=[post_id]
        )
        == []
    )


def test_delete_cited_post_returns_409_with_report_title(client, created_posts):
    _login(client)
    post_id = _make_post("被报告引用的帖子")
    created_posts.append(post_id)

    title = "Test Weekly Report (delete guard)"
    with Session(get_engine()) as session:
        report = Report(title=title)
        session.add(report)
        session.flush()
        block = ReportBlock(
            report_id=report.id,
            section="brand_watch",
            block_type="claim",
            text_content="Claim text citing the post.",
        )
        session.add(block)
        session.flush()
        # Citation in the SAME transaction: the deferred DB trigger requires
        # every claim block to carry at least one citation at commit.
        session.add(ReportCitation(block_id=block.id, post_id=uuid.UUID(post_id)))
        session.commit()
        report_id = str(report.id)

    try:
        response = client.delete(f"/api/posts/{post_id}")
        assert response.status_code == 409
        body = response.get_json()
        assert title in body["error"]
        assert body["reports"] == [{"id": report_id, "title": title}]
        with Session(get_engine()) as session:
            assert session.get(Post, uuid.UUID(post_id)) is not None  # survived
    finally:
        with Session(get_engine()) as session:
            report = session.get(Report, uuid.UUID(report_id))
            if report is not None:
                session.delete(report)  # blocks + citations cascade
            session.commit()


def test_delete_unknown_post_returns_404_and_unauth_401(client):
    assert client.delete(f"/api/posts/{uuid.uuid4()}").status_code == 401
    _login(client)
    assert client.delete(f"/api/posts/{uuid.uuid4()}").status_code == 404


# ---------------------------------------------------------------------------
# LocalMediaStore.delete
# ---------------------------------------------------------------------------


def test_local_media_store_delete_is_safe_and_idempotent(tmp_path):
    store = LocalMediaStore(str(tmp_path))
    relative = store.save(b"bytes", "shot.png")
    assert store.exists(relative)

    store.delete(relative)
    assert not store.exists(relative)
    store.delete(relative)  # missing file is a no-op

    with pytest.raises(ValueError):
        store.delete("../outside.png")
