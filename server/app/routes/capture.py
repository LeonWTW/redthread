"""Capture routes. Minimal single/multi-image capture in M1 (task 1.5); hardened in M2.

POST /api/capture accepts multipart form data: 0..20 files under "images",
optional "caption", "image_type", "url", "defer_pipeline". A URL that parses to
an already-captured xhs_note_id returns 200 already_captured and creates
nothing. Every accepted capture creates a posts row (plus post_images rows with
perceptual hashes), reports SOFT near-duplicate warnings, and enqueues the
OCR -> translate chain (unless defer_pipeline=1), returning 202.

POST /api/import/csv bulk-creates posts from analyst-curated rows (url,
caption, captured_at, notes). This is manual curation import — the system
never fetches any URL or performs automated collection.
"""

from __future__ import annotations

import csv
import datetime
import io
import uuid

from flask import Blueprint, jsonify, request

from app.db import SessionLocal, get_engine
from app.models import Annotation, Post, PostImage
from app.phash import UnreadableImageError, compute_phash_signed, find_near_duplicates
from app.providers import registry
from app.security import session_or_token_required, session_required
from app.xhs import parse_xhs_note_id

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


def _read_and_hash(storage) -> tuple[bytes, int]:
    """Read a file's bytes and compute the signed 64-bit pHash.

    Raises UnreadableImageError for bytes PIL cannot decode.
    """
    file_bytes = storage.read()
    return file_bytes, compute_phash_signed(file_bytes)


@capture_bp.post("/capture")
@session_or_token_required
def capture():
    files = [f for f in request.files.getlist("images") if f and f.filename]
    caption = (request.form.get("caption") or "").strip() or None
    url = (request.form.get("url") or "").strip() or None
    defer_pipeline = request.form.get("defer_pipeline") == "1"

    if not files and not caption and not url:
        return jsonify(error="provide at least one image, a caption, or a url"), 400
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

    get_engine()
    session = SessionLocal()

    # URL dedup: an already-captured note id short-circuits; create NOTHING.
    xhs_note_id = parse_xhs_note_id(url) if url else None
    if xhs_note_id is not None:
        existing = session.query(Post).filter_by(xhs_note_id=xhs_note_id).first()
        if existing is not None:
            return jsonify(already_captured=True, post_id=str(existing.id)), 200

    # Read bytes and compute pHashes before anything is persisted.
    payloads: list[tuple[bytes, int]] = []
    for index, storage in enumerate(files):
        try:
            payloads.append(_read_and_hash(storage))
        except UnreadableImageError as exc:
            return jsonify(error=f"file {index} ({storage.filename}): {exc}"), 400

    # Near-duplicate scan against EXISTING rows only (soft warnings).
    near_duplicates = []
    for index, (_, signed_hash) in enumerate(payloads):
        matches = find_near_duplicates(session, signed_hash)
        if matches:
            near_duplicates.append({"image_index": index, "matches": matches})

    media_store = registry.get_media_store()
    saved: list[str] = []  # file_path per file, in upload order
    for storage, (file_bytes, _) in zip(files, payloads):
        suggested_name = f"{uuid.uuid4().hex}.{_extension(storage.filename)}"
        saved.append(media_store.save(file_bytes, suggested_name))

    post = Post(caption_raw=caption, source_url=url, xhs_note_id=xhs_note_id)
    post.images = [
        PostImage(
            sort_order=index,
            image_type=image_type,
            file_path=file_path,
            perceptual_hash=payloads[index][1],
        )
        for index, file_path in enumerate(saved)
    ]
    session.add(post)
    session.commit()
    post_id = str(post.id)

    if not defer_pipeline:
        from app.pipeline.tasks import enqueue_slice_chain

        enqueue_slice_chain(post_id)
    return jsonify(post_id=post_id, near_duplicates=near_duplicates), 202


@capture_bp.post("/import/csv")
@session_required
def import_csv():
    """CSV import: analyst-curated rows. Columns (any order): url, caption,
    captured_at, notes; only url is required per row. Row numbers are 1-based
    data rows."""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="provide a CSV file under the 'file' field"), 400

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify(error="CSV file must be UTF-8 encoded"), 400

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "url" not in reader.fieldnames:
        return jsonify(error="CSV header row must include a 'url' column"), 400

    get_engine()
    session = SessionLocal()

    created = 0
    duplicates: list[dict] = []
    errors: list[dict] = []

    for row_number, row in enumerate(reader, start=1):
        url = (row.get("url") or "").strip()
        if not url:
            errors.append({"row": row_number, "error": "missing url"})
            continue

        caption = (row.get("caption") or "").strip() or None
        notes = (row.get("notes") or "").strip() or None
        captured_at_raw = (row.get("captured_at") or "").strip()

        captured_at = None
        if captured_at_raw:
            try:
                captured_at = datetime.datetime.fromisoformat(
                    captured_at_raw.replace("Z", "+00:00")
                )
            except ValueError:
                errors.append(
                    {"row": row_number, "error": f"invalid captured_at: {captured_at_raw!r}"}
                )
                continue

        xhs_note_id = parse_xhs_note_id(url)
        if xhs_note_id is not None:
            existing = session.query(Post).filter_by(xhs_note_id=xhs_note_id).first()
            if existing is not None:
                duplicates.append({"row": row_number, "post_id": str(existing.id)})
                continue

        post = Post(source_url=url, xhs_note_id=xhs_note_id, caption_raw=caption)
        if captured_at is not None:
            post.captured_at = captured_at
        session.add(post)
        session.flush()
        if notes:
            annotation = (
                session.query(Annotation).filter_by(post_id=post.id).first()
            )
            if annotation is None:
                session.add(Annotation(post_id=post.id, notes=notes))
            else:
                annotation.notes = notes
        session.commit()
        created += 1

        # Caption-only translation; URL-only rows have nothing to process yet.
        if caption:
            from app.pipeline.tasks import enqueue_slice_chain

            enqueue_slice_chain(str(post.id))

    return jsonify(created=created, duplicates=duplicates, errors=errors), 200
