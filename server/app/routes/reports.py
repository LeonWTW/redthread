"""Report builder routes (M6 tasks 6.1/6.4, plan 001).

Iron law #5: the report builder cannot generate a claim without a citation.
The API validates BEFORE insert (clear 400s) and writes a claim block plus its
citations in ONE transaction; the deferred DB constraint triggers in schema.sql
remain the structural backstop, never the expected error path.

Template IA (locked, CLAUDE.md section 5): brand_watch, trend_radar,
not_crossing, decoder, seen_in_china. The decoder section is rendered from the
glossary table and carries NO blocks — any block targeting it is rejected.
Trend blocks (Crossover Screen) live only in trend_radar; claims may nest
under a trend via parent_block_id.
"""

from __future__ import annotations

import datetime
import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, get_engine
from app.models import (
    GlossaryTerm,
    Post,
    Report,
    ReportBlock,
    ReportCitation,
    crossover_verdict_enum,
    report_section_enum,
)
from app.security import session_required

reports_bp = Blueprint("reports", __name__, url_prefix="/api")

# Sections that can carry blocks. decoder is rendered from the glossary table
# (locked template IA) and never accepts blocks.
_BLOCK_SECTIONS = tuple(s for s in report_section_enum.enums if s != "decoder")

_BLOCK_TYPES = ("claim", "trend")

# Crossover Screen: exactly these four factors (locked trend-level component).
_CROSSOVER_KEYS = frozenset(
    {
        "visual_legibility",
        "price_shipability",
        "creator_translatability",
        "institutional_carrier",
    }
)

_SNIPPET_LENGTH = 80

_BLOCK_PATCH_FIELDS = (
    "text_content",
    "trend_title",
    "crossover",
    "crossover_verdict",
    "sort_order",
    "citations",
)


# ---------------------------------------------------------------------------
# JSON payload helpers
# ---------------------------------------------------------------------------


def _snippet(text: str | None) -> str | None:
    return text[:_SNIPPET_LENGTH] if text else None


def _citation_json(citation: ReportCitation) -> dict:
    """Citation chip payload. Requires citation.post (+ images) to be loaded.

    zh_snippet keeps the source Chinese (bilingual evidence chain is a core
    selling point); en_snippet prefers the analyst's final translation.
    """
    post = citation.post
    images = sorted(post.images, key=lambda image: image.sort_order)
    first_image = images[0] if images else None
    return {
        "post_id": str(post.id),
        "zh_snippet": _snippet(
            post.corrected_text or post.full_ocr_text or post.caption_raw
        ),
        "en_snippet": _snippet(post.final_translation or post.machine_translation),
        "first_image_url": ("/media/" + first_image.file_path) if first_image else None,
    }


def _block_json(block: ReportBlock, children: list[ReportBlock] | None = None) -> dict:
    payload = {
        "id": str(block.id),
        "section": block.section,
        "sort_order": block.sort_order,
        "block_type": block.block_type,
        "text_content": block.text_content,
        "trend_title": block.trend_title,
        "crossover": block.crossover,
        "crossover_verdict": block.crossover_verdict,
        "parent_block_id": str(block.parent_block_id) if block.parent_block_id else None,
        "citations": [_citation_json(c) for c in block.citations],
    }
    if block.block_type == "trend":
        payload["children"] = [_block_json(child) for child in (children or [])]
    return payload


def _report_summary(report: Report, block_count: int) -> dict:
    return {
        "id": str(report.id),
        "title": report.title,
        "week_of": report.week_of.isoformat() if report.week_of else None,
        "status": report.status,
        "block_count": block_count,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


def _block_query(session):
    """Blocks with citations -> posts -> images eagerly loaded (no N+1)."""
    return session.query(ReportBlock).options(
        selectinload(ReportBlock.citations)
        .selectinload(ReportCitation.post)
        .selectinload(Post.images)
    )


def _load_block(session, block_id: uuid.UUID) -> ReportBlock | None:
    # populate_existing: sessions run with expire_on_commit=False, so a reload
    # after commit must overwrite the identity map's stale citations collection.
    return (
        _block_query(session)
        .populate_existing()
        .filter(ReportBlock.id == block_id)
        .one_or_none()
    )


def _load_children(session, block: ReportBlock) -> list[ReportBlock]:
    if block.block_type != "trend":
        return []
    return (
        _block_query(session)
        .populate_existing()
        .filter(ReportBlock.parent_block_id == block.id)
        .order_by(ReportBlock.sort_order)
        .all()
    )


# ---------------------------------------------------------------------------
# Validation helpers (all run BEFORE any insert; DB triggers are the backstop)
# ---------------------------------------------------------------------------


def _validate_crossover_fields(body: dict) -> str | None:
    """Validate crossover / crossover_verdict when present (None clears)."""
    crossover = body.get("crossover")
    if crossover is not None:
        if not isinstance(crossover, dict) or set(crossover) != _CROSSOVER_KEYS:
            return (
                "crossover must be an object with exactly these keys: "
                f"{sorted(_CROSSOVER_KEYS)}"
            )
        if not all(isinstance(value, str) for value in crossover.values()):
            return "crossover factor values must be strings"
    verdict = body.get("crossover_verdict")
    if verdict is not None and verdict not in crossover_verdict_enum.enums:
        return (
            f"invalid crossover_verdict '{verdict}': must be one of "
            f"{list(crossover_verdict_enum.enums)}"
        )
    return None


def _parse_citation_ids(raw) -> tuple[list[uuid.UUID] | None, str | None]:
    if not isinstance(raw, list):
        return None, "citations must be an array of post ids"
    ids: list[uuid.UUID] = []
    for item in raw:
        try:
            post_id = uuid.UUID(str(item))
        except (ValueError, AttributeError, TypeError):
            return None, f"invalid post id in citations: '{item}'"
        if post_id not in ids:
            ids.append(post_id)
    return ids, None


def _missing_post_ids(session, post_ids: list[uuid.UUID]) -> list[str]:
    if not post_ids:
        return []
    found = {
        row[0]
        for row in session.query(Post.id).filter(Post.id.in_(post_ids)).all()
    }
    return [str(pid) for pid in post_ids if pid not in found]


def _next_sort_order(session, report_id, section, parent_block_id) -> int:
    current = (
        session.query(func.max(ReportBlock.sort_order))
        .filter(
            ReportBlock.report_id == report_id,
            ReportBlock.section == section,
            ReportBlock.parent_block_id == parent_block_id,
        )
        .scalar()
    )
    return 0 if current is None else current + 1


def _parse_week_of(value) -> tuple[datetime.date | None, str | None]:
    if value is None:
        return None, None
    try:
        return datetime.date.fromisoformat(str(value)), None
    except ValueError:
        return None, "week_of must be an ISO date (YYYY-MM-DD) or null"


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


@reports_bp.post("/reports")
@session_required
def create_report():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        return jsonify(error="title is required and must be a non-empty string"), 400
    week_of, error = _parse_week_of(body.get("week_of"))
    if error is not None:
        return jsonify(error=error), 400

    get_engine()
    session = SessionLocal()
    report = Report(title=title.strip(), week_of=week_of)
    session.add(report)
    session.commit()
    return jsonify(_report_summary(report, block_count=0)), 201


@reports_bp.get("/reports")
@session_required
def list_reports():
    get_engine()
    session = SessionLocal()
    rows = (
        session.query(Report, func.count(ReportBlock.id))
        .outerjoin(ReportBlock, ReportBlock.report_id == Report.id)
        .group_by(Report.id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return jsonify(reports=[_report_summary(r, count) for r, count in rows])


@reports_bp.get("/reports/<uuid:report_id>")
@session_required
def get_report(report_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    report = session.get(Report, report_id)
    if report is None:
        return jsonify(error="report not found"), 404

    blocks = (
        _block_query(session)
        .filter(ReportBlock.report_id == report_id)
        .order_by(ReportBlock.sort_order)
        .all()
    )
    children_by_parent: dict[uuid.UUID, list[ReportBlock]] = {}
    for block in blocks:
        if block.parent_block_id is not None:
            children_by_parent.setdefault(block.parent_block_id, []).append(block)

    # Fixed template order; decoder renders from the glossary and has no blocks.
    sections: dict[str, list[dict]] = {s: [] for s in _BLOCK_SECTIONS}
    for block in blocks:
        if block.parent_block_id is not None:
            continue  # nested claims appear under their trend, not top-level
        sections[block.section].append(
            _block_json(block, children_by_parent.get(block.id, []))
        )

    return jsonify(
        id=str(report.id),
        title=report.title,
        week_of=report.week_of.isoformat() if report.week_of else None,
        status=report.status,
        sections=sections,
    )


@reports_bp.patch("/reports/<uuid:report_id>")
@session_required
def update_report(report_id: uuid.UUID):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400
    for field in body:
        if field not in ("title", "week_of", "status"):
            return jsonify(
                error=f"unknown field '{field}': must be one of ['title', 'week_of', 'status']"
            ), 400
    if "title" in body and (
        not isinstance(body["title"], str) or not body["title"].strip()
    ):
        return jsonify(error="title must be a non-empty string"), 400
    if "status" in body and body["status"] not in ("draft", "final"):
        return jsonify(error="status must be 'draft' or 'final'"), 400
    week_of = None
    if "week_of" in body:
        week_of, error = _parse_week_of(body["week_of"])
        if error is not None:
            return jsonify(error=error), 400

    get_engine()
    session = SessionLocal()
    report = session.get(Report, report_id)
    if report is None:
        return jsonify(error="report not found"), 404
    if "title" in body:
        report.title = body["title"].strip()
    if "week_of" in body:
        report.week_of = week_of
    if "status" in body:
        report.status = body["status"]
    session.commit()

    block_count = (
        session.query(func.count(ReportBlock.id))
        .filter(ReportBlock.report_id == report_id)
        .scalar()
    )
    return jsonify(_report_summary(report, block_count))


@reports_bp.delete("/reports/<uuid:report_id>")
@session_required
def delete_report(report_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    report = session.get(Report, report_id)
    if report is None:
        return jsonify(error="report not found"), 404
    # Bulk delete: blocks, nested blocks, and citations all cascade at the DB
    # layer (schema.sql FKs), which sidesteps ORM self-referential ordering.
    session.query(Report).filter(Report.id == report_id).delete(
        synchronize_session=False
    )
    session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


@reports_bp.post("/reports/<uuid:report_id>/blocks")
@session_required
def create_block(report_id: uuid.UUID):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400

    section = body.get("section")
    if section == "decoder":
        return jsonify(
            error="the decoder section is rendered from the glossary table and cannot carry blocks"
        ), 400
    if section not in _BLOCK_SECTIONS:
        return jsonify(
            error=f"invalid section '{section}': must be one of {list(_BLOCK_SECTIONS)}"
        ), 400

    block_type = body.get("block_type")
    if block_type not in _BLOCK_TYPES:
        return jsonify(
            error=f"invalid block_type '{block_type}': must be one of {list(_BLOCK_TYPES)}"
        ), 400

    text_content = body.get("text_content")
    trend_title = body.get("trend_title")
    if block_type == "claim":
        if not isinstance(text_content, str) or not text_content.strip():
            return jsonify(error="a claim block requires non-empty text_content"), 400
    else:  # trend
        if section != "trend_radar":
            return jsonify(error="trend blocks are only allowed in trend_radar"), 400
        if not isinstance(trend_title, str) or not trend_title.strip():
            return jsonify(error="a trend block requires non-empty trend_title"), 400

    error = _validate_crossover_fields(body)
    if error is not None:
        return jsonify(error=error), 400

    citation_ids: list[uuid.UUID] = []
    if block_type == "claim" or body.get("citations") is not None:
        parsed, error = _parse_citation_ids(body.get("citations") or [])
        if error is not None:
            return jsonify(error=error), 400
        citation_ids = parsed
    if block_type == "claim" and not citation_ids:
        return jsonify(
            error="a claim block requires at least one citation (iron law #5: "
            "every claim traces to a captured post)"
        ), 400

    sort_order = body.get("sort_order")
    if sort_order is not None and (
        isinstance(sort_order, bool) or not isinstance(sort_order, int)
    ):
        return jsonify(error="sort_order must be an integer"), 400

    parent_id: uuid.UUID | None = None
    if body.get("parent_block_id") is not None:
        if block_type != "claim":
            return jsonify(error="only claim blocks may nest under a trend"), 400
        try:
            parent_id = uuid.UUID(str(body["parent_block_id"]))
        except ValueError:
            return jsonify(error="parent_block_id must be a UUID"), 400

    get_engine()
    session = SessionLocal()
    report = session.get(Report, report_id)
    if report is None:
        return jsonify(error="report not found"), 404

    if parent_id is not None:
        parent = session.get(ReportBlock, parent_id)
        if (
            parent is None
            or parent.block_type != "trend"
            or parent.report_id != report_id
        ):
            return jsonify(
                error="parent_block_id must be a trend block in the same report"
            ), 400

    missing = _missing_post_ids(session, citation_ids)
    if missing:
        return jsonify(
            error=f"citations reference unknown post id(s): {', '.join(missing)}"
        ), 400

    if sort_order is None:
        sort_order = _next_sort_order(session, report_id, section, parent_id)

    # Block + citations in ONE transaction: the deferred claim_requires_citation
    # trigger checks at COMMIT, so a validated claim always lands with its chips.
    block = ReportBlock(
        report_id=report_id,
        section=section,
        sort_order=sort_order,
        block_type=block_type,
        parent_block_id=parent_id,
        text_content=text_content,
        trend_title=trend_title,
        crossover=body.get("crossover"),
        crossover_verdict=body.get("crossover_verdict"),
    )
    session.add(block)
    try:
        session.flush()
        for post_id in citation_ids:
            session.add(ReportCitation(block_id=block.id, post_id=post_id))
        session.commit()
    except IntegrityError:
        # Backstop only (e.g. a post deleted between validation and commit).
        session.rollback()
        return jsonify(
            error="citation constraint violated at commit (iron law #5)"
        ), 400

    block_id = block.id
    block = _load_block(session, block_id)
    return jsonify(_block_json(block, _load_children(session, block))), 201


@reports_bp.patch("/blocks/<uuid:block_id>")
@session_required
def update_block(block_id: uuid.UUID):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="request body must be a JSON object"), 400
    for field in body:
        if field not in _BLOCK_PATCH_FIELDS:
            return jsonify(
                error=f"unknown field '{field}': must be one of {list(_BLOCK_PATCH_FIELDS)}"
            ), 400

    get_engine()
    session = SessionLocal()
    block = _load_block(session, block_id)
    if block is None:
        return jsonify(error="block not found"), 404

    # --- validate everything BEFORE touching the DB --------------------------
    if "text_content" in body and block.block_type == "claim":
        value = body["text_content"]
        if not isinstance(value, str) or not value.strip():
            return jsonify(error="a claim block requires non-empty text_content"), 400
    if "trend_title" in body:
        if block.block_type != "trend":
            return jsonify(error="trend_title only applies to trend blocks"), 400
        value = body["trend_title"]
        if not isinstance(value, str) or not value.strip():
            return jsonify(error="a trend block requires non-empty trend_title"), 400
    error = _validate_crossover_fields(body)
    if error is not None:
        return jsonify(error=error), 400
    if "sort_order" in body and (
        isinstance(body["sort_order"], bool) or not isinstance(body["sort_order"], int)
    ):
        return jsonify(error="sort_order must be an integer"), 400

    citation_ids: list[uuid.UUID] | None = None
    if "citations" in body:
        citation_ids, error = _parse_citation_ids(body["citations"])
        if error is not None:
            return jsonify(error=error), 400
        if block.block_type == "claim" and not citation_ids:
            return jsonify(
                error="a claim block must retain at least one citation (iron law #5)"
            ), 400
        missing = _missing_post_ids(session, citation_ids)
        if missing:
            return jsonify(
                error=f"citations reference unknown post id(s): {', '.join(missing)}"
            ), 400

    # --- apply (one transaction; citations REPLACE the set via diff) ---------
    for field in ("text_content", "trend_title", "crossover", "crossover_verdict",
                  "sort_order"):
        if field in body:
            setattr(block, field, body[field])
    if citation_ids is not None:
        current = {citation.post_id: citation for citation in block.citations}
        wanted = set(citation_ids)
        for post_id, citation in current.items():
            if post_id not in wanted:
                session.delete(citation)
        for post_id in citation_ids:
            if post_id not in current:
                session.add(ReportCitation(block_id=block.id, post_id=post_id))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return jsonify(
            error="citation constraint violated at commit (iron law #5)"
        ), 400

    block = _load_block(session, block_id)
    return jsonify(_block_json(block, _load_children(session, block)))


@reports_bp.delete("/blocks/<uuid:block_id>")
@session_required
def delete_block(block_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    block = session.get(ReportBlock, block_id)
    if block is None:
        return jsonify(error="block not found"), 404
    # Bulk delete: citations cascade; children of a trend cascade via the
    # parent_block_id FK (schema.sql). The deferred citation_delete_guard
    # allows this because the claim block itself is gone at commit time.
    session.query(ReportBlock).filter(ReportBlock.id == block_id).delete(
        synchronize_session=False
    )
    session.commit()
    return "", 204


# ---------------------------------------------------------------------------
# Glossary (read-only: feeds the Decoder section preview)
# ---------------------------------------------------------------------------


@reports_bp.get("/glossary")
@session_required
def list_glossary():
    get_engine()
    session = SessionLocal()
    terms = session.query(GlossaryTerm).order_by(GlossaryTerm.term_zh).all()
    return jsonify(
        terms=[
            {
                "term_zh": term.term_zh,
                "term_en": term.term_en,
                "note": term.note,
                "category": term.category,
            }
            for term in terms
        ]
    )
