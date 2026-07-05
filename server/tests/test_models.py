"""Model tests against the live compose Postgres (schema already applied).

Tests create their own rows and delete them on the way out; nothing they
insert survives the test run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Annotation, Post, PostImage


@pytest.fixture()
def session():
    engine = get_engine()
    with Session(engine) as s:
        yield s
        s.rollback()


def test_post_image_annotation_roundtrip(session):
    marker = f"test-note-{uuid.uuid4()}"
    post = Post(
        xhs_note_id=marker,
        source_url="https://www.xiaohongshu.com/explore/abc",
        caption_raw="测试贴文 caption",
    )
    # Insert out of order to prove the relationship orders by sort_order.
    post.images = [
        PostImage(sort_order=1, image_type="comments", file_path="m/2.png"),
        PostImage(sort_order=0, file_path="m/1.png", raw_ocr="原始 OCR 文本"),
    ]
    post.annotation = Annotation(
        category="makeup",
        consumer_signal="zhongcao",
        origin=None,  # skip = NULL is explicitly allowed
        notes="roundtrip test",
    )
    session.add(post)
    session.commit()
    post_id = post.id

    try:
        session.expire_all()
        fetched = session.get(Post, post_id)
        assert fetched is not None
        assert fetched.platform == "xhs"  # server default
        assert fetched.ocr_status == "pending"  # server default
        assert fetched.captured_at is not None

        # Post.images ordered by sort_order.
        assert [img.sort_order for img in fetched.images] == [0, 1]
        assert fetched.images[0].raw_ocr == "原始 OCR 文本"
        assert fetched.images[0].image_type == "note_content"  # server default
        assert fetched.images[1].image_type == "comments"
        assert fetched.images[0].post is fetched

        # One-to-one annotation.
        assert fetched.annotation is not None
        assert fetched.annotation.category == "makeup"
        assert fetched.annotation.consumer_signal == "zhongcao"
        assert fetched.annotation.origin is None
        assert fetched.annotation.post is fetched
    finally:
        session.delete(session.get(Post, post_id))
        session.commit()

    # Cascade removed children.
    assert session.get(Post, post_id) is None
    assert (
        session.scalars(select(PostImage).where(PostImage.post_id == post_id)).first()
        is None
    )
    assert (
        session.scalars(
            select(Annotation).where(Annotation.post_id == post_id)
        ).first()
        is None
    )


def test_two_posts_with_null_xhs_note_id_allowed(session):
    """The unique index on xhs_note_id is partial (WHERE xhs_note_id IS NOT NULL);
    multiple NULLs must coexist."""
    p1 = Post(xhs_note_id=None, caption_raw="null note id 1")
    p2 = Post(xhs_note_id=None, caption_raw="null note id 2")
    session.add_all([p1, p2])
    session.commit()

    try:
        assert p1.id != p2.id
        assert p1.xhs_note_id is None and p2.xhs_note_id is None
    finally:
        session.delete(p1)
        session.delete(p2)
        session.commit()
