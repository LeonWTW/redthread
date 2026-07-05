"""Report export routes (M7 task 7.2, plan 001).

GET /api/reports/<id>/export      -> self-contained HTML (deliverable|public)
GET /api/reports/<id>/export.pdf  -> Playwright-rendered PDF of the deliverable
Both are analyst-session-only, like every other route.
"""

from __future__ import annotations

import re
import uuid

from flask import Blueprint, Response, jsonify, request

from app.export import (
    PdfRendererUnavailable,
    load_export_data,
    render_pdf,
    render_report_html,
)
from app.export.template import VARIANTS
from app.security import session_required

export_bp = Blueprint("export", __name__, url_prefix="/api")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "report"


@export_bp.get("/reports/<uuid:report_id>/export")
@session_required
def export_html(report_id: uuid.UUID):
    variant = request.args.get("variant", "deliverable")
    if variant not in VARIANTS:
        return jsonify(
            error=f"invalid variant '{variant}': must be one of {list(VARIANTS)}"
        ), 400
    data = load_export_data(report_id)
    if data is None:
        return jsonify(error="report not found"), 404
    return Response(render_report_html(data, variant=variant), mimetype="text/html")


@export_bp.get("/reports/<uuid:report_id>/export.pdf")
@session_required
def export_pdf(report_id: uuid.UUID):
    data = load_export_data(report_id)
    if data is None:
        return jsonify(error="report not found"), 404
    html = render_report_html(data, variant="deliverable")
    try:
        pdf_bytes = render_pdf(html)
    except PdfRendererUnavailable as exc:
        return jsonify(error=f"pdf renderer unavailable: {exc}"), 503
    filename = f"{_slugify(data['report']['title'])}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
