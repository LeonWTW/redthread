"""Export data loading (M7 task 7.1).

Reuses the report-builder block query (routes/reports.py) so the export reads
exactly the same shapes the editor does. Global citation numbering lives ONLY
here: markers are numbered in reading order (fixed section order, then
sort_order, then each block's citations), deduplicated by source post — citing
the same post twice reuses its number and its single Evidence appendix entry.
"""

from __future__ import annotations

import datetime
import uuid

from app.db import SessionLocal, get_engine
from app.models import GlossaryTerm, Report, ReportBlock
from app.routes.reports import _block_query

# Locked template IA (CLAUDE.md section 5): fixed order, decoder renders from
# the glossary table, seen_in_china is omitted entirely when empty.
SECTION_ORDER = (
    "brand_watch",
    "trend_radar",
    "not_crossing",
    "decoder",
    "seen_in_china",
)
SECTION_TITLES = {
    "brand_watch": "C-beauty Brand Watch",
    "trend_radar": "Trend Radar",
    "not_crossing": "Not Crossing",
    "decoder": "Consumer Language Decoder",
    "seen_in_china": "Seen in China",
}

# Crossover Screen: four locked factors, fixed display order.
CROSSOVER_FACTORS = (
    ("visual_legibility", "Visual legibility"),
    ("price_shipability", "Price & shipability"),
    ("creator_translatability", "Creator translatability"),
    ("institutional_carrier", "Institutional carrier"),
)
VERDICT_LABELS = {
    "will_cross": "Will cross",
    "wont_cross": "Won't cross",
    "watch": "Watch",
}

# Appendix snippets are longer than the editor's 80-char chips: the export is
# the evidence chain a client actually reads.
_SNIPPET_LENGTH = 300


def _snippet(text: str | None) -> str | None:
    if not text:
        return None
    if len(text) <= _SNIPPET_LENGTH:
        return text
    return text[:_SNIPPET_LENGTH].rstrip() + "…"


def format_date(value: datetime.date) -> str:
    """'30 June 2026' — no platform-dependent strftime day padding."""
    return f"{value.day} {value.strftime('%B %Y')}"


class _SourceNumberer:
    """Assigns global citation numbers in reading order, deduped by post."""

    def __init__(self) -> None:
        self._by_post: dict[uuid.UUID, int] = {}
        self.sources: list[dict] = []

    def assign(self, citation) -> int:
        post = citation.post
        existing = self._by_post.get(post.id)
        if existing is not None:
            return existing
        number = len(self.sources) + 1
        self._by_post[post.id] = number
        # Bilingual evidence, Chinese FIRST (source Chinese is core product
        # value); same fallback chains as the editor's citation chips.
        self.sources.append(
            {
                "number": number,
                "post_id": str(post.id),
                "zh": _snippet(
                    post.corrected_text or post.full_ocr_text or post.caption_raw
                ),
                "en": _snippet(post.final_translation or post.machine_translation),
                "captured_label": (
                    format_date(post.captured_at.date()) if post.captured_at else None
                ),
                "note_id": post.xhs_note_id,
            }
        )
        return number


def load_export_data(report_id: uuid.UUID) -> dict | None:
    """Full export payload for one report, or None when it does not exist."""
    get_engine()
    session = SessionLocal()
    report = session.get(Report, report_id)
    if report is None:
        return None

    blocks = (
        _block_query(session)
        .populate_existing()
        .filter(ReportBlock.report_id == report_id)
        .order_by(ReportBlock.sort_order)
        .all()
    )
    children_by_parent: dict[uuid.UUID, list[ReportBlock]] = {}
    top_by_section: dict[str, list[ReportBlock]] = {key: [] for key in SECTION_ORDER}
    for block in blocks:
        if block.parent_block_id is not None:
            children_by_parent.setdefault(block.parent_block_id, []).append(block)
        else:
            top_by_section[block.section].append(block)

    numberer = _SourceNumberer()

    def claim_dict(block: ReportBlock) -> dict:
        return {
            "type": "claim",
            "text": block.text_content,
            "cites": [numberer.assign(c) for c in block.citations],
        }

    def trend_dict(block: ReportBlock) -> dict:
        cites = [numberer.assign(c) for c in block.citations]
        crossover = None
        if block.crossover:
            crossover = [
                {"label": label, "value": block.crossover.get(key, "")}
                for key, label in CROSSOVER_FACTORS
            ]
        verdict = None
        if block.crossover_verdict:
            verdict = {
                "key": block.crossover_verdict,
                "label": VERDICT_LABELS[block.crossover_verdict],
            }
        return {
            "type": "trend",
            "title": block.trend_title,
            "summary": block.text_content,
            "cites": cites,
            "crossover": crossover,
            "verdict": verdict,
            "children": [
                claim_dict(child) for child in children_by_parent.get(block.id, [])
            ],
        }

    sections: list[dict] = []
    number = 0
    for key in SECTION_ORDER:
        if key == "decoder":
            number += 1
            sections.append(
                {"key": key, "number": number, "title": SECTION_TITLES[key]}
            )
            continue
        section_blocks = [
            trend_dict(block) if block.block_type == "trend" else claim_dict(block)
            for block in top_by_section[key]
        ]
        if key == "seen_in_china" and not section_blocks:
            continue  # optional section: omitted entirely when empty
        number += 1
        sections.append(
            {
                "key": key,
                "number": number,
                "title": SECTION_TITLES[key],
                "blocks": section_blocks,
            }
        )

    glossary = [
        {"term_zh": term.term_zh, "term_en": term.term_en, "note": term.note}
        for term in session.query(GlossaryTerm).order_by(GlossaryTerm.term_zh).all()
    ]

    return {
        "report": {
            "title": report.title,
            "week_of_label": (
                f"Week of {format_date(report.week_of)}" if report.week_of else None
            ),
            "status": report.status,
        },
        "sections": sections,
        "glossary": glossary,
        "sources": numberer.sources,
    }
