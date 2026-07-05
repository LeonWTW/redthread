"""Post routes: read + M2 append-image/process + M3 list, retry, corrections.

M3 contract (plan 001 tasks 3.4/3.5):
- POST /api/posts/<id>/process enqueues the FULL 4-step chain, force=False
  (skip-on-success makes repeats safe).
- POST /api/posts/<id>/retry/<step> enqueues steps <step>..embed, all force=True.
- PATCH /api/posts/<id> persists analyst corrections; a changed corrected_text
  or final_translation enqueues a forced re-embed (iron law #2).
- PATCH /api/posts/<id>/images/<image_id> stores a per-image corrected_ocr;
  the post-level corrected_text remains the analyst's authoritative aggregate.
- GET /api/posts lists posts for the Inbox (captured_at DESC).
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, get_engine
from app.models import Post, PostImage
from app.phash import UnreadableImageError, compute_phash_signed, find_near_duplicates
from app.providers import registry
from app.security import session_or_token_required, session_required

posts_bp = Blueprint("posts", __name__, url_prefix="/api")

_PIPELINE_STEPS = ("ocr", "translate", "extract", "embed")
_ENTITY_KEYS = ("text_zh", "text_en", "type", "confidence")


def _post_json(post: Post) -> dict:
    """Full post payload shared by GET /posts/<id> and PATCH /posts/<id>."""
    payload = {
        "id": str(post.id),
        "platform": post.platform,
        "captured_at": post.captured_at.isoformat() if post.captured_at else None,
        "caption_raw": post.caption_raw,
        "full_ocr_text": post.full_ocr_text,
        "corrected_text": post.corrected_text,
        "machine_translation": post.machine_translation,
        "final_translation": post.final_translation,
        "entities": post.entities,
        "images": [
            {
                "id": str(image.id),
                "sort_order": image.sort_order,
                "image_type": image.image_type,
                "url": "/media/" + image.file_path,
            }
            for image in post.images
        ],
    }
    for step in _PIPELINE_STEPS:
        payload[f"{step}_status"] = getattr(post, f"{step}_status")
        payload[f"{step}_error_type"] = getattr(post, f"{step}_error_type")
        payload[f"{step}_error_message"] = getattr(post, f"{step}_error_message")
    return payload


@posts_bp.get("/posts/<uuid:post_id>")
@session_required
def get_post(post_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404
    return jsonify(_post_json(post))


@posts_bp.get("/posts")
@session_required
def list_posts():
    """Inbox listing: newest first, per-step status + error surface."""
    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)
    limit = max(0, min(limit if limit is not None else 50, 200))
    offset = max(0, offset if offset is not None else 0)

    get_engine()
    session = SessionLocal()
    total = session.query(Post).count()
    posts = (
        session.query(Post)
        .options(selectinload(Post.images), selectinload(Post.annotation))
        .order_by(Post.captured_at.desc(), Post.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    items = []
    for post in posts:
        images = sorted(post.images, key=lambda image: image.sort_order)
        first_image = images[0] if images else None
        item = {
            "id": str(post.id),
            "captured_at": post.captured_at.isoformat() if post.captured_at else None,
            "caption_raw": post.caption_raw[:120] if post.caption_raw else None,
            "xhs_note_id": post.xhs_note_id,
            "image_count": len(images),
            "first_image_url": ("/media/" + first_image.file_path) if first_image else None,
            "has_annotation": post.annotation is not None,
        }
        for step in _PIPELINE_STEPS:
            item[f"{step}_status"] = getattr(post, f"{step}_status")
            item[f"{step}_error_type"] = getattr(post, f"{step}_error_type")
            item[f"{step}_error_message"] = getattr(post, f"{step}_error_message")
        items.append(item)
    return jsonify(posts=items, total=total)


@posts_bp.post("/posts/<uuid:post_id>/images")
@session_or_token_required
def append_image(post_id: uuid.UUID):
    """Append one image to an existing post (mobile sequential-upload flow)."""
    from app.routes.capture import _IMAGE_TYPES, _extension, _validate_file

    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    storage = request.files.get("image")
    if storage is None or not storage.filename:
        return jsonify(error="provide one file under the 'image' field"), 400

    error = _validate_file(storage)
    if error is not None:
        body, status = error
        return jsonify(**body), status

    image_type = request.form.get("image_type") or "note_content"
    if image_type not in _IMAGE_TYPES:
        return jsonify(
            error=f"invalid image_type '{image_type}': must be one of {sorted(_IMAGE_TYPES)}"
        ), 400

    file_bytes = storage.read()
    try:
        signed_hash = compute_phash_signed(file_bytes)
    except UnreadableImageError as exc:
        return jsonify(error=f"file ({storage.filename}): {exc}"), 400

    # Near-duplicate scan against EXISTING rows only (soft warnings).
    near_duplicates = find_near_duplicates(session, signed_hash)

    media_store = registry.get_media_store()
    file_path = media_store.save(
        file_bytes, f"{uuid.uuid4().hex}.{_extension(storage.filename)}"
    )

    next_sort_order = max((img.sort_order for img in post.images), default=-1) + 1
    image = PostImage(
        post_id=post.id,
        sort_order=next_sort_order,
        image_type=image_type,
        file_path=file_path,
        perceptual_hash=signed_hash,
    )
    session.add(image)
    session.commit()

    return jsonify(image_id=str(image.id), near_duplicates=near_duplicates), 202


@posts_bp.post("/posts/<uuid:post_id>/process")
@session_or_token_required
def process_post(post_id: uuid.UUID):
    """Enqueue the full OCR -> translate -> extract -> embed chain (force=False).

    Safe to call repeatedly: steps already 'success' skip without touching data.
    """
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404
    pid = str(post.id)

    from app.pipeline.tasks import enqueue_slice_chain

    enqueue_slice_chain(pid)
    return jsonify(post_id=pid), 202


@posts_bp.post("/posts/<uuid:post_id>/retry/<step>")
@session_or_token_required
def retry_step(post_id: uuid.UUID, step: str):
    """Enqueue steps <step>..embed, ALL with force=True (design note 002:
    upstream changed => downstream machine outputs are stale by definition)."""
    if step not in _PIPELINE_STEPS:
        return jsonify(
            error=f"unknown step '{step}': must be one of {list(_PIPELINE_STEPS)}"
        ), 400

    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404
    pid = str(post.id)

    from app.pipeline.tasks import build_chain

    steps = list(_PIPELINE_STEPS[_PIPELINE_STEPS.index(step):])
    # Reset the retried step + downstream to pending (and clear their error
    # taxonomy) BEFORE enqueueing, so the Inbox never shows stale failed/success
    # states for steps that are queued to re-run (design note 002 addendum).
    for step_name in steps:
        setattr(post, f"{step_name}_status", "pending")
        setattr(post, f"{step_name}_error_type", None)
        setattr(post, f"{step_name}_error_message", None)
    session.commit()
    build_chain(pid, from_step=step, force=True).apply_async()
    return jsonify(post_id=pid, steps=steps), 202


def _validate_entities(value) -> str | None:
    """Return an error message unless value is a JSON array of entity objects."""
    if not isinstance(value, list):
        return "entities must be a JSON array"
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return f"entities[{index}] must be an object"
        missing = [key for key in _ENTITY_KEYS if key not in item]
        if missing:
            return f"entities[{index}] missing keys: {', '.join(missing)}"
        if not all(isinstance(item[key], str) for key in ("text_zh", "text_en", "type")):
            return f"entities[{index}]: text_zh, text_en, and type must be strings"
        confidence = item["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            return f"entities[{index}]: confidence must be a number"
    return None


@posts_bp.patch("/posts/<uuid:post_id>")
@session_required
def update_post(post_id: uuid.UUID):
    """Persist analyst corrections. A CHANGED corrected_text or
    final_translation enqueues a forced re-embed (iron law #2); editing
    entities alone does not (entities are not part of the embed document)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400
    if "entities" in body:
        error = _validate_entities(body["entities"])
        if error is not None:
            return jsonify(error=error), 400

    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    reembed = False
    for field in ("corrected_text", "final_translation"):
        if field in body and body[field] != getattr(post, field):
            setattr(post, field, body[field])
            reembed = True
    if "entities" in body:
        post.entities = body["entities"]
    session.commit()

    # Build the response BEFORE enqueueing: in eager test mode the task runs
    # inline and tears down the scoped session.
    payload = _post_json(post)
    if reembed:
        from app.pipeline.tasks import embed_post

        embed_post.delay(str(post_id), True)
    return jsonify(payload)


@posts_bp.patch("/posts/<uuid:post_id>/images/<uuid:image_id>")
@session_required
def update_post_image(post_id: uuid.UUID, image_id: uuid.UUID):
    """Store a per-image OCR correction. Does NOT re-aggregate or re-embed:
    the post-level corrected_text remains the analyst's authoritative aggregate."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or "corrected_ocr" not in body:
        return jsonify(error="provide 'corrected_ocr' in a JSON body"), 400
    corrected = body["corrected_ocr"]
    if corrected is not None and not isinstance(corrected, str):
        return jsonify(error="corrected_ocr must be a string or null"), 400

    get_engine()
    session = SessionLocal()
    image = session.get(PostImage, image_id)
    if image is None or image.post_id != post_id:
        return jsonify(error="image not found"), 404

    image.corrected_ocr = corrected
    session.commit()
    return jsonify(image_id=str(image.id)), 200
