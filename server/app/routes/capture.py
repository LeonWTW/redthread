"""Capture routes. Minimal single/multi-image capture in M1 (task 1.5); hardened in M2.

POST /api/capture accepts multipart form data: 1..20 files under "images",
optional "caption", optional "image_type" (applied to all files). Caption-only
capture (no files) is allowed. Every accepted capture creates a posts row (plus
post_images rows) and enqueues the OCR -> translate chain, returning 202.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request

from app.db import SessionLocal, get_engine
from app.models import Post, PostImage
from app.providers import registry
from app.security import session_or_token_required

capture_bp = Blueprint("capture", __name__, url_prefix="/api")

MAX_FILES = 20
_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_ALLOWED_MIMETYPES = {"image/png", "image/jpeg", "image/webp"}
_HEIC_EXTENSIONS = {"heic", "heif"}
_HEIC_MIMETYPES = {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"}
_IMAGE_TYPES = {"note_content", "comments", "other"}

HEIC_MESSAGE = (
    "HEIC/HEIF images are not supported. "
    "Please upload a screenshot (PNG or JPEG) instead."
)


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _validate_file(storage) -> tuple[dict, int] | None:
    """Return (error_json, http_status) for a bad file, or None if acceptable."""
    ext = _extension(storage.filename or "")
    mimetype = (storage.mimetype or "").lower()
    if ext in _HEIC_EXTENSIONS or mimetype in _HEIC_MIMETYPES:
        return {"error": HEIC_MESSAGE}, 415
    if ext not in _ALLOWED_EXTENSIONS:
        return {
            "error": f"unsupported file type '.{ext}': only PNG, JPEG, and WebP are accepted"
        }, 400
    # Browsers may send application/octet-stream; the extension check above governs.
    if mimetype and mimetype != "application/octet-stream" and mimetype not in _ALLOWED_MIMETYPES:
        return {
            "error": f"unsupported content type '{mimetype}': only PNG, JPEG, and WebP are accepted"
        }, 400
    return None


@capture_bp.post("/capture")
@session_or_token_required
def capture():
    files = [f for f in request.files.getlist("images") if f and f.filename]
    caption = (request.form.get("caption") or "").strip() or None

    if not files and not caption:
        return jsonify(error="provide at least one image or a caption"), 400
    if len(files) > MAX_FILES:
        return jsonify(error=f"too many files: max {MAX_FILES} images per capture"), 400

    image_type = request.form.get("image_type") or "note_content"
    if image_type not in _IMAGE_TYPES:
        return jsonify(
            error=f"invalid image_type '{image_type}': must be one of {sorted(_IMAGE_TYPES)}"
        ), 400

    for storage in files:
        error = _validate_file(storage)
        if error is not None:
            body, status = error
            return jsonify(**body), status

    media_store = registry.get_media_store()
    saved: list[str] = []  # file_path per file, in upload order
    for storage in files:
        suggested_name = f"{uuid.uuid4().hex}.{_extension(storage.filename)}"
        saved.append(media_store.save(storage.read(), suggested_name))

    get_engine()
    session = SessionLocal()
    post = Post(caption_raw=caption)
    post.images = [
        PostImage(sort_order=index, image_type=image_type, file_path=file_path)
        for index, file_path in enumerate(saved)
    ]
    session.add(post)
    session.commit()
    post_id = str(post.id)

    from app.pipeline.tasks import enqueue_slice_chain

    enqueue_slice_chain(post_id)
    return jsonify(post_id=post_id), 202
