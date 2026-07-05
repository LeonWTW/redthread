"""M4 annotation tests (plan 001 task 4.3): PUT upsert endpoint, enum
validation, the has_annotation / order query params on GET /api/posts, and
the annotation field on GET /api/posts/<id>.

Posts are created directly via SQLAlchemy (no pipeline involved) and every
test deletes its rows afterwards (annotations cascade with the post).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from sqlalchemy.orm import Session

from app import create_app
from app.db import get_engine
from app.models import Annotation, Post

_ENUM_FIELDS = (
    "category", "trend_type", "consumer_signal", "recommended_action", "origin"
)
_ANNOTATION_KEYS = {"post_id", "notes", *_ENUM_FIELDS}


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
    client = app.test_client()
    response = client.post(
        "/api/login", json={"username": "analyst", "password": "test-password"}
    )
    assert 200 <= response.status_code < 300
    return client


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


def _make_post(created_posts, captured_at: datetime.datetime | None = None) -> str:
    with Session(get_engine()) as session:
        post = Post(caption_raw="测试 caption")
        if captured_at is not None:
            post.captured_at = captured_at
        session.add(post)
        session.commit()
        post_id = str(post.id)
    created_posts.append(post_id)
    return post_id


def _annotation_row_count(post_id: str) -> int:
    with Session(get_engine()) as session:
        return (
            session.query(Annotation)
            .filter(Annotation.post_id == uuid.UUID(post_id))
            .count()
        )


# ---------------------------------------------------------------------------
# PUT /api/posts/<id>/annotation — upsert roundtrip
# ---------------------------------------------------------------------------


def test_upsert_create_update_clear_roundtrip(client, created_posts):
    post_id = _make_post(created_posts)

    # Create: subset of fields; the rest default to NULL (skip is legal).
    response = client.put(
        f"/api/posts/{post_id}/annotation",
        json={"category": "makeup", "consumer_signal": "zhongcao", "notes": "种草 note"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == _ANNOTATION_KEYS
    assert body == {
        "post_id": post_id,
        "category": "makeup",
        "trend_type": None,
        "consumer_signal": "zhongcao",
        "recommended_action": None,
        "origin": None,
        "notes": "种草 note",
    }
    assert _annotation_row_count(post_id) == 1

    # Update: only the present key changes; absent keys stay untouched.
    response = client.put(
        f"/api/posts/{post_id}/annotation", json={"category": "skincare"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["category"] == "skincare"
    assert body["consumer_signal"] == "zhongcao"
    assert body["notes"] == "种草 note"
    assert _annotation_row_count(post_id) == 1  # upsert, not a second row

    # Explicit null clears a field without touching the others.
    response = client.put(
        f"/api/posts/{post_id}/annotation",
        json={"consumer_signal": None, "notes": None},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["consumer_signal"] is None
    assert body["notes"] is None
    assert body["category"] == "skincare"
    assert _annotation_row_count(post_id) == 1


def test_notes_only_annotation(client, created_posts):
    post_id = _make_post(created_posts)
    response = client.put(
        f"/api/posts/{post_id}/annotation", json={"notes": "避雷 warning only"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["notes"] == "避雷 warning only"
    for field in _ENUM_FIELDS:
        assert body[field] is None


# ---------------------------------------------------------------------------
# PUT validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "offending_field"),
    [
        ({"category": "fragrance"}, "category"),
        ({"trend_type": "meme"}, "trend_type"),
        ({"consumer_signal": "种草"}, "consumer_signal"),  # slug, not Chinese
        ({"recommended_action": "ignore"}, "recommended_action"),
        ({"origin": "mars"}, "origin"),
        ({"virality_score": 9000}, "virality_score"),  # unknown field
        ({"notes": 42}, "notes"),  # non-string notes
    ],
)
def test_invalid_field_returns_400_naming_it(
    client, created_posts, payload, offending_field
):
    post_id = _make_post(created_posts)
    response = client.put(f"/api/posts/{post_id}/annotation", json=payload)
    assert response.status_code == 400
    assert offending_field in response.get_json()["error"]
    assert _annotation_row_count(post_id) == 0  # nothing persisted


def test_upsert_unknown_post_404(client):
    response = client.put(
        f"/api/posts/{uuid.uuid4()}/annotation", json={"category": "makeup"}
    )
    assert response.status_code == 404


def test_upsert_requires_session(app):
    anonymous = app.test_client()
    response = anonymous.put(
        f"/api/posts/{uuid.uuid4()}/annotation", json={"category": "makeup"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/posts — has_annotation filter and order param
# ---------------------------------------------------------------------------


def test_has_annotation_filter(client, created_posts):
    annotated_id = _make_post(created_posts)
    plain_id = _make_post(created_posts)
    response = client.put(
        f"/api/posts/{annotated_id}/annotation", json={"category": "haircare"}
    )
    assert response.status_code == 200

    listed_true = client.get("/api/posts?has_annotation=true&limit=200").get_json()
    ids_true = {item["id"] for item in listed_true["posts"]}
    assert annotated_id in ids_true
    assert plain_id not in ids_true

    listed_false = client.get("/api/posts?has_annotation=false&limit=200").get_json()
    ids_false = {item["id"] for item in listed_false["posts"]}
    assert plain_id in ids_false
    assert annotated_id not in ids_false

    response = client.get("/api/posts?has_annotation=maybe")
    assert response.status_code == 400


def test_order_asc(client, created_posts):
    utc = datetime.timezone.utc
    # Dates far in the past so ascending order puts them at the front even
    # when the shared dev database contains other posts.
    older_id = _make_post(created_posts, datetime.datetime(2020, 1, 1, tzinfo=utc))
    newer_id = _make_post(created_posts, datetime.datetime(2020, 1, 2, tzinfo=utc))

    body = client.get("/api/posts?order=asc&limit=200").get_json()
    order = [item["id"] for item in body["posts"]]
    assert order.index(older_id) < order.index(newer_id)

    body = client.get("/api/posts?order=desc&limit=200").get_json()
    order = [item["id"] for item in body["posts"]]
    assert order.index(newer_id) < order.index(older_id)

    response = client.get("/api/posts?order=sideways")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/posts/<id> — annotation field
# ---------------------------------------------------------------------------


def test_get_post_includes_annotation(client, created_posts):
    post_id = _make_post(created_posts)

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["annotation"] is None

    saved = client.put(
        f"/api/posts/{post_id}/annotation",
        json={"category": "wellness", "origin": "china_native", "notes": "成分党 angle"},
    ).get_json()

    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["annotation"] == saved
    assert body["annotation"]["origin"] == "china_native"
