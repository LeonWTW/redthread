"""Pipeline tasks: the M1 two-step chain (OCR -> translate).

Every step is idempotent and independently retryable (iron law #3):
- ocr_post only OCRs images whose raw_ocr IS NULL; the post aggregate is
  recomputed deterministically, so re-running after success leaves state intact.
- translate_post overwrites machine_translation (a machine output), never
  final_translation (the analyst's field).

Retry semantics: TransientProviderError self-retries max 2 times with
exponential backoff (10s, 30s) then fails; other ProviderErrors fail
immediately. The step status + error taxonomy is ALWAYS written to the posts
row before the task raises or returns; a failing step stops the chain.
"""

from __future__ import annotations

import uuid

from celery import chain

from app.db import SessionLocal, get_engine
from app.models import GlossaryTerm as GlossaryRow
from app.models import Post
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import GlossaryTerm, ProviderError, TransientProviderError

COMMENT_MARKER = "--- Below is from the comment section ---"

# Exponential backoff (seconds) indexed by retry count so far.
_RETRY_COUNTDOWNS = (10, 30)
_MAX_RETRIES = 2


def _set_step(session, post: Post, step: str, status: str,
              error_type: str | None = None, error_message: str | None = None) -> None:
    """Write one step's status + error taxonomy and commit immediately."""
    setattr(post, f"{step}_status", status)
    setattr(post, f"{step}_error_type", error_type)
    setattr(post, f"{step}_error_message", error_message)
    session.commit()


def _handle_provider_error(task, session, post: Post, step: str, exc: ProviderError):
    """Persist the failure per retry policy, then raise to stop the chain."""
    if isinstance(exc, TransientProviderError) and task.request.retries < _MAX_RETRIES:
        # Status stays 'running' while a retry is pending; taxonomy is recorded.
        _set_step(session, post, step, "running", exc.error_type, str(exc))
        countdown = _RETRY_COUNTDOWNS[min(task.request.retries, len(_RETRY_COUNTDOWNS) - 1)]
        raise task.retry(exc=exc, countdown=countdown, max_retries=_MAX_RETRIES)
    _set_step(session, post, step, "failed", exc.error_type, str(exc))
    raise exc


@celery.task(bind=True, name="pipeline.ocr_post", max_retries=_MAX_RETRIES)
def ocr_post(self, post_id: str) -> str:
    """OCR every image lacking raw_ocr, then aggregate posts.full_ocr_text."""
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"

        images = sorted(post.images, key=lambda i: i.sort_order)
        if not images:
            if post.caption_raw:
                # Caption-only post: nothing to OCR; translation runs on the caption.
                _set_step(session, post, "ocr", "skipped")
                return "skipped"
            # Neither images nor caption: stop the chain quietly, stay pending.
            _set_step(session, post, "ocr", "pending")
            self.request.chain = None
            self.request.callbacks = None
            return "awaiting_media"

        _set_step(session, post, "ocr", "running")

        media_store = registry.get_media_store()
        provider = registry.get_ocr_provider()
        try:
            for image in images:
                if image.raw_ocr is not None:
                    continue  # idempotency: never re-OCR or overwrite raw_ocr
                file_bytes = media_store.open(image.file_path)
                mime = _mime_for(image.file_path)
                image.raw_ocr = provider.ocr_image(file_bytes, mime)
                session.commit()
        except ProviderError as exc:
            _handle_provider_error(self, session, post, "ocr", exc)
        except Exception as exc:  # unexpected: record, fail the step, stop the chain
            _set_step(session, post, "ocr", "failed", "storage_error", str(exc))
            raise

        # Deterministic aggregate: note_content + other in sort_order, then comments.
        note_parts = [
            img.raw_ocr for img in images
            if img.image_type in ("note_content", "other") and img.raw_ocr
        ]
        comment_parts = [
            img.raw_ocr for img in images
            if img.image_type == "comments" and img.raw_ocr
        ]
        full_text = "\n\n".join(note_parts)
        if comment_parts:
            full_text = (full_text + "\n" if full_text else "") \
                + COMMENT_MARKER + "\n" + "\n\n".join(comment_parts)
        post.full_ocr_text = full_text
        _set_step(session, post, "ocr", "success")
        return "success"
    finally:
        SessionLocal.remove()


@celery.task(bind=True, name="pipeline.translate_post", max_retries=_MAX_RETRIES)
def translate_post(self, post_id: str) -> str:
    """Translate the aggregated zh text; overwrite machine_translation only."""
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"

        ocr_side = post.corrected_text or post.full_ocr_text or ""
        if post.caption_raw and ocr_side:
            zh_text = post.caption_raw + "\n\n" + ocr_side
        else:
            zh_text = post.caption_raw or ocr_side
        if not zh_text:
            # Nothing to translate (awaiting media); stay pending, stop quietly.
            _set_step(session, post, "translate", "pending")
            return "awaiting_source"

        _set_step(session, post, "translate", "running")

        glossary = [
            GlossaryTerm(term_zh=row.term_zh, term_en=row.term_en, note=row.note)
            for row in session.query(GlossaryRow).order_by(GlossaryRow.term_zh).all()
        ]
        provider = registry.get_translation_provider()
        try:
            translation = provider.translate(zh_text, glossary)
        except ProviderError as exc:
            _handle_provider_error(self, session, post, "translate", exc)
        except Exception as exc:
            _set_step(session, post, "translate", "failed", "storage_error", str(exc))
            raise

        post.machine_translation = translation  # never touches final_translation
        _set_step(session, post, "translate", "success")
        return "success"
    finally:
        SessionLocal.remove()


def enqueue_slice_chain(post_id: str):
    """Enqueue the M1 vertical-slice chain for one post (used by capture)."""
    return chain(ocr_post.si(post_id), translate_post.si(post_id)).apply_async()


def _mime_for(file_path: str) -> str:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
