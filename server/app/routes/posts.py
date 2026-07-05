"""Post routes: read (M1 task 1.5) plus M2 append-image and process endpoints."""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from app.db import SessionLocal, get_engine
from app.models import Post, PostImage
from app.phash import UnreadableImageError, compute_phash_signed, find_near_duplicates
from app.providers import registry
from app.security import session_or_token_required, session_required

posts_bp = Blueprint("posts", __name__, url_prefix="/api")


@posts_bp.get("/posts/<uuid:post_id>")
@session_required
def get_post(post_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    return jsonify(
        id=str(post.id),
        platform=post.platform,
        captured_at=post.captured_at.isoformat() if post.captured_at else None,
        caption_raw=post.caption_raw,
        full_ocr_text=post.full_ocr_text,
        corrected_text=post.corrected_text,
        machine_translation=post.machine_translation,
        final_translation=post.final_translation,
        entities=post.entities,
        ocr_status=post.ocr_status,
        translate_status=post.translate_status,
        extract_status=post.extract_status,
        embed_status=post.embed_status,
        ocr_error_type=post.ocr_error_type,
        ocr_error_message=post.ocr_error_message,
        translate_error_type=post.translate_error_type,
        translate_error_message=post.translate_error_message,
        extract_error_type=post.extract_error_type,
        extract_error_message=post.extract_error_message,
        embed_error_type=post.embed_error_type,
        embed_error_message=post.embed_error_message,
        images=[
            {
                "id": str(image.id),
                "sort_order": image.sort_order,
                "image_type": image.image_type,
                "url": "/media/" + image.file_path,
            }
            for image in post.images
        ],
    )


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
    """Enqueue the OCR -> translate chain; safe to call repeatedly (idempotent tasks)."""
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    from app.pipeline.tasks import enqueue_slice_chain

    enqueue_slice_chain(str(post.id))
    return jsonify(post_id=str(post.id)), 202
