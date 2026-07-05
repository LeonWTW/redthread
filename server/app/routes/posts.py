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

M5 (plan 001 task 5.1):
- DELETE /api/posts/<id> removes the row (images + annotation cascade), its
  media files, and its Qdrant point. A post cited in a report CANNOT be
  deleted (report_citations FK is ON DELETE RESTRICT by design): the response
  is 409 carrying the citing report titles, never a workaround.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import vectors

from app.db import SessionLocal, get_engine
from app.models import (
    Annotation,
    Post,
    PostImage,
    Report,
    ReportBlock,
    ReportCitation,
    category_enum,
    consumer_signal_enum,
    origin_enum,
    recommended_action_enum,
    trend_type_enum,
)
from app.phash import UnreadableImageError, compute_phash_signed, find_near_duplicates
from app.providers import registry
from app.security import session_or_token_required, session_required

posts_bp = Blueprint("posts", __name__, url_prefix="/api")

_PIPELINE_STEPS = ("ocr", "translate", "extract", "embed")
_ENTITY_KEYS = ("text_zh", "text_en", "type", "confidence")

# Locked v1 taxonomy (schema.sql is the source of truth; the ENUM objects in
# app.models mirror it, so validation lists come from there, never hardcoded).
_ANNOTATION_ENUM_FIELDS = {
    "category": category_enum,
    "trend_type": trend_type_enum,
    "consumer_signal": consumer_signal_enum,
    "recommended_action": recommended_action_enum,
    "origin": origin_enum,
}
_ANNOTATION_FIELDS = (*_ANNOTATION_ENUM_FIELDS, "notes")


def _annotation_json(post: Post) -> dict | None:
    """Annotation payload for a post, or None when not yet annotated."""
    annotation = post.annotation
    if annotation is None:
        return None
    payload = {"post_id": str(post.id), "notes": annotation.notes}
    for field in _ANNOTATION_ENUM_FIELDS:
        payload[field] = getattr(annotation, field)
    return payload


def _post_card(post: Post) -> dict:
    """Card payload shared by the Inbox listing and Library search results,
    so the two screens can never drift apart. Requires images + annotation
    to be loaded (selectinload) to avoid N+1 queries."""
    images = sorted(post.images, key=lambda image: image.sort_order)
    first_image = images[0] if images else None
    card = {
        "id": str(post.id),
        "captured_at": post.captured_at.isoformat() if post.captured_at else None,
        "caption_raw": post.caption_raw[:120] if post.caption_raw else None,
        "xhs_note_id": post.xhs_note_id,
        "image_count": len(images),
        "first_image_url": ("/media/" + first_image.file_path) if first_image else None,
        "has_annotation": post.annotation is not None,
    }
    for step in _PIPELINE_STEPS:
        card[f"{step}_status"] = getattr(post, f"{step}_status")
        card[f"{step}_error_type"] = getattr(post, f"{step}_error_type")
        card[f"{step}_error_message"] = getattr(post, f"{step}_error_message")
    return card


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
        "annotation": _annotation_json(post),
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
    """Inbox/Triage listing: per-step status + error surface, optional
    has_annotation filter and captured_at ordering (default newest first)."""
    limit = request.args.get("limit", default=50, type=int)
    offset = request.args.get("offset", default=0, type=int)
    limit = max(0, min(limit if limit is not None else 50, 200))
    offset = max(0, offset if offset is not None else 0)

    has_annotation = request.args.get("has_annotation")
    if has_annotation is not None and has_annotation not in ("true", "false"):
        return jsonify(error="has_annotation must be 'true' or 'false'"), 400
    order = request.args.get("order", default="desc")
    if order not in ("asc", "desc"):
        return jsonify(error="order must be 'asc' or 'desc'"), 400

    get_engine()
    session = SessionLocal()
    query = session.query(Post)
    if has_annotation == "true":
        query = query.filter(Post.annotation.has())
    elif has_annotation == "false":
        query = query.filter(~Post.annotation.has())
    total = query.count()
    if order == "asc":
        ordering = (Post.captured_at.asc(), Post.created_at.asc())
    else:
        ordering = (Post.captured_at.desc(), Post.created_at.desc())
    posts = (
        query
        .options(selectinload(Post.images), selectinload(Post.annotation))
        .order_by(*ordering)
        .limit(limit)
        .offset(offset)
        .all()
    )

    return jsonify(posts=[_post_card(post) for post in posts], total=total)


def _citing_reports(session, post_id: uuid.UUID) -> list[dict]:
    """Reports whose claim blocks cite this post (drives the 409 payload)."""
    rows = (
        session.query(Report.id, Report.title)
        .join(ReportBlock, ReportBlock.report_id == Report.id)
        .join(ReportCitation, ReportCitation.block_id == ReportBlock.id)
        .filter(ReportCitation.post_id == post_id)
        .distinct()
        .all()
    )
    return [{"id": str(report_id), "title": title} for report_id, title in rows]


@posts_bp.delete("/posts/<uuid:post_id>")
@session_required
def delete_post(post_id: uuid.UUID):
    """Delete a post plus its media files and Qdrant point.

    Order matters: the DB row is the source of truth, so it goes first; media
    and vector cleanup follow (both idempotent, so a partial failure can be
    retried). Cited posts are protected by the ON DELETE RESTRICT FK — checked
    up front for a friendly 409, with IntegrityError as belt-and-braces
    against a citation added concurrently."""
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    def cited_response(reports: list[dict]):
        titles = ", ".join(report["title"] for report in reports)
        return jsonify(
            error=f"post is cited in report(s): {titles}", reports=reports
        ), 409

    reports = _citing_reports(session, post_id)
    if reports:
        return cited_response(reports)

    file_paths = [image.file_path for image in post.images]
    try:
        session.delete(post)
        session.commit()
    except IntegrityError:
        # Citation added between our check and the delete: the RESTRICT FK wins.
        session.rollback()
        return cited_response(_citing_reports(session, post_id))

    media_store = registry.get_media_store()
    for file_path in file_paths:
        media_store.delete(file_path)
    vectors.delete_post(str(post_id))  # tolerates an absent point/collection
    return "", 204


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


@posts_bp.put("/posts/<uuid:post_id>/annotation")
@session_required
def upsert_annotation(post_id: uuid.UUID):
    """UPSERT the single annotation row for a post (Triage save, M4 contract).

    Any subset of {category, trend_type, consumer_signal, recommended_action,
    origin, notes} is accepted; keys absent from the body are left untouched,
    an explicit null clears a field (skip = NULL is legal taxonomy)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400
    for field, value in body.items():
        if field not in _ANNOTATION_FIELDS:
            return jsonify(
                error=f"unknown field '{field}': must be one of {list(_ANNOTATION_FIELDS)}"
            ), 400
        if value is None:
            continue
        if field == "notes":
            if not isinstance(value, str):
                return jsonify(error="notes must be a string or null"), 400
        elif value not in _ANNOTATION_ENUM_FIELDS[field].enums:
            return jsonify(
                error=f"invalid {field} '{value}': must be one of "
                f"{list(_ANNOTATION_ENUM_FIELDS[field].enums)} or null"
            ), 400

    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    annotation = post.annotation
    if annotation is None:
        # Assign through the relationship (not session.add) so the already-
        # loaded post.annotation is populated for the response payload
        # (sessions run with expire_on_commit=False).
        annotation = Annotation(post_id=post.id)
        post.annotation = annotation
    for field, value in body.items():
        setattr(annotation, field, value)
    session.commit()
    return jsonify(_annotation_json(post)), 200


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
