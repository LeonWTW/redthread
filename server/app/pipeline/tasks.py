"""Pipeline tasks: the M3 four-step chain (OCR -> translate -> extract -> embed).

Semantics per design note 002 (docs/plans/002-pipeline-idempotency.md):
- Every task takes (post_id, force=False). With force=False a step whose
  status is already 'success' returns immediately without touching data, so
  re-enqueuing the whole chain is always safe. force=True (explicit per-step
  retry) re-runs the step and overwrites its own MACHINE outputs only.
- Retrying step N enqueues steps N..embed all with force=True (upstream
  changed => downstream outputs are stale by definition).
- Machine outputs vs analyst fields: ocr_post only OCRs images whose raw_ocr
  IS NULL and recomputes the deterministic aggregate; translate/extract/embed
  overwrite only machine_translation / entities / the Qdrant point — never
  corrected_text, final_translation, or corrected_ocr.
- Retry policy: TransientProviderError self-retries max 2 times with backoff
  (10s, 30s) then fails; other ProviderErrors fail immediately. Step status +
  error taxonomy is ALWAYS written before the task raises or returns; a
  failing step stops the chain.
"""

from __future__ import annotations

import datetime
import uuid

from celery import chain

from app import vectors
from app.db import SessionLocal, get_engine
from app.models import GlossaryTerm as GlossaryRow
from app.models import Post
from app.pipeline.celery_app import celery
from app.providers import registry
from app.providers.base import GlossaryTerm, ProviderError, TransientProviderError

COMMENT_MARKER = "--- Below is from the comment section ---"

STEPS = ("ocr", "translate", "extract", "embed")

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


def _skip_completed(post: Post, step: str, force: bool) -> bool:
    """force=False + step already 'success' -> skip without touching data."""
    return not force and getattr(post, f"{step}_status") == "success"


def _zh_source(post: Post) -> str:
    """Shared zh source: caption_raw + blank line + (corrected_text || full_ocr_text).

    Either side may be absent; the comment-section marker lives inside the OCR
    aggregate. Used by translate, extract, and embed.
    """
    ocr_side = post.corrected_text or post.full_ocr_text or ""
    caption = post.caption_raw or ""
    if caption and ocr_side:
        return caption + "\n\n" + ocr_side
    return caption or ocr_side


def _en_side(post: Post) -> str:
    """English side: analyst's final_translation wins over the machine output."""
    return post.final_translation or post.machine_translation or ""


@celery.task(bind=True, name="pipeline.ocr_post", max_retries=_MAX_RETRIES)
def ocr_post(self, post_id: str, force: bool = False) -> str:
    """OCR every image lacking raw_ocr, then aggregate posts.full_ocr_text.

    Under force, raw_ocr of previously-OCR'd images is still preserved: force
    re-runs only missing images and always recomputes the deterministic
    aggregate.
    """
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"
        if _skip_completed(post, "ocr", force):
            return "already_success"

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
def translate_post(self, post_id: str, force: bool = False) -> str:
    """Translate the aggregated zh text; overwrite machine_translation only."""
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"
        if _skip_completed(post, "translate", force):
            return "already_success"

        zh_text = _zh_source(post)
        if not zh_text:
            # Nothing to translate (awaiting media); stay pending, stop quietly.
            _set_step(session, post, "translate", "pending")
            self.request.chain = None
            self.request.callbacks = None
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


@celery.task(bind=True, name="pipeline.extract_post", max_retries=_MAX_RETRIES)
def extract_post(self, post_id: str, force: bool = False) -> str:
    """Extract bilingual entities into posts.entities (machine output).

    Design note 002 tradeoff: entities is one JSONB column shared by machine
    output and analyst edits; nothing overwrites it except first successful
    extract (skip-on-success protects it) and an explicit forced retry.
    """
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"
        if _skip_completed(post, "extract", force):
            return "already_success"

        zh_text = _zh_source(post)
        en_text = _en_side(post)
        if not zh_text and not en_text:
            _set_step(session, post, "extract", "skipped")
            return "skipped"

        _set_step(session, post, "extract", "running")

        provider = registry.get_extraction_provider()
        try:
            entities = provider.extract(zh_text, en_text)
        except ProviderError as exc:
            _handle_provider_error(self, session, post, "extract", exc)
        except Exception as exc:
            _set_step(session, post, "extract", "failed", "storage_error", str(exc))
            raise

        post.entities = [entity.__dict__ for entity in entities]
        _set_step(session, post, "extract", "success")
        return "success"
    finally:
        SessionLocal.remove()


@celery.task(bind=True, name="pipeline.embed_post", max_retries=_MAX_RETRIES)
def embed_post(self, post_id: str, force: bool = False) -> str:
    """Embed the bilingual concat and upsert the post's Qdrant point.

    Document (pinned, plan 001 §1): zh source + "\\n---\\n" + english side.
    Skipped only when BOTH sides are empty. embedded_at is set on success.
    """
    get_engine()
    session = SessionLocal()
    try:
        post = session.get(Post, uuid.UUID(post_id))
        if post is None:
            return "missing"
        if _skip_completed(post, "embed", force):
            return "already_success"

        zh_text = _zh_source(post)
        en_text = _en_side(post)
        if not zh_text and not en_text:
            _set_step(session, post, "embed", "skipped")
            return "skipped"
        document = zh_text + "\n---\n" + en_text

        _set_step(session, post, "embed", "running")

        provider = registry.get_embedding_provider()
        try:
            vector = provider.embed(document)
        except ProviderError as exc:
            _handle_provider_error(self, session, post, "embed", exc)
        except Exception as exc:
            _set_step(session, post, "embed", "failed", "storage_error", str(exc))
            raise

        try:
            # Upsert keyed by post UUID: re-embedding replaces the point.
            vectors.upsert_post(post_id, vector)
        except Exception as exc:
            _set_step(session, post, "embed", "failed", "storage_error", str(exc))
            raise

        post.embedded_at = datetime.datetime.now(datetime.timezone.utc)
        _set_step(session, post, "embed", "success")
        return "success"
    finally:
        SessionLocal.remove()


_TASK_BY_STEP = {
    "ocr": ocr_post,
    "translate": translate_post,
    "extract": extract_post,
    "embed": embed_post,
}


def build_chain(post_id: str, from_step: str = "ocr", force: bool = False):
    """Celery chain of steps from_step..embed, all with the given force flag."""
    if from_step not in STEPS:
        raise ValueError(f"unknown pipeline step: {from_step}")
    selected = STEPS[STEPS.index(from_step):]
    return chain(*(_TASK_BY_STEP[step].si(post_id, force) for step in selected))


def enqueue_slice_chain(post_id: str):
    """Backward-compatible entry point: enqueue the FULL chain with force=False."""
    return build_chain(post_id).apply_async()


def _mime_for(file_path: str) -> str:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
