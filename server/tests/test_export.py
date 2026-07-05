"""M7 tasks 7.1/7.2 tests: report export (HTML variants + PDF smoke).

The HTML tests need no browser. The single PDF smoke test skips gracefully
when Chromium is unavailable in the test container. Every test cleans up the
DB rows it creates; glossary seed rows are canonical data and stay.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from markupsafe import escape
from sqlalchemy.orm import Session

from app import create_app
from app.db import get_engine
from app.models import Post, Report

SEED_SQL = Path(__file__).resolve().parents[1] / "seeds" / "glossary.sql"

ZH_A = "唇泥质地测试：珂拉琪的雾面唇泥非常显色，但是容易拔干，建议叠加润唇膏使用。"
EN_A = "Lip mud texture test: Colorkey's matte lip mud is very pigmented but drying."
ZH_B = "种草了花知晓的新腮红，包装是真的绝。"
EN_B = "Planted on Flower Knows' new blush; the packaging is stunning."

_CROSSOVER = {
    "visual_legibility": "High: the lip-mud finish reads instantly on camera.",
    "price_shipability": "Under $15 and lightweight; easy to ship.",
    "creator_translatability": "Western creators can replicate the swatch format.",
    "institutional_carrier": "No retail carrier yet; DTC only.",
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("ANALYST_USERNAME", "analyst")
    monkeypatch.setenv("ANALYST_PASSWORD", "test-password")
    return create_app(
        {"TESTING": True, "SESSION_COOKIE_SECURE": False, "RATELIMIT_ENABLED": False}
    )


@pytest.fixture()
def client(app):
    client = app.test_client()
    response = client.post(
        "/api/login", json={"username": "analyst", "password": "test-password"}
    )
    assert 200 <= response.status_code < 300
    return client


@pytest.fixture()
def cleanup():
    """Track created report/post ids; reports go first (citations RESTRICT posts)."""
    created = {"reports": [], "posts": []}
    yield created
    with Session(get_engine()) as session:
        for report_id in created["reports"]:
            session.query(Report).filter(Report.id == uuid.UUID(report_id)).delete(
                synchronize_session=False
            )
        session.commit()
    with Session(get_engine()) as session:
        for post_id in created["posts"]:
            post = session.get(Post, uuid.UUID(post_id))
            if post is not None:
                session.delete(post)
        session.commit()


def _make_post(cleanup, **fields) -> str:
    with Session(get_engine()) as session:
        post = Post(**fields)
        session.add(post)
        session.commit()
        post_id = str(post.id)
    cleanup["posts"].append(post_id)
    return post_id


def _make_report(client, cleanup, title="Export Test Weekly Report", **extra) -> str:
    response = client.post("/api/reports", json={"title": title, **extra})
    assert response.status_code == 201
    report_id = response.get_json()["id"]
    cleanup["reports"].append(report_id)
    return report_id


def _add_block(client, report_id, payload) -> dict:
    response = client.post(f"/api/reports/{report_id}/blocks", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


@pytest.fixture()
def full_report(client, cleanup):
    """Report exercising every section except seen_in_china (left empty).

    post_a is cited twice (brand_watch claim AND nested trend claim) to prove
    global numbering dedupes by source post.
    """
    with get_engine().begin() as connection:  # idempotent glossary seed
        connection.exec_driver_sql(SEED_SQL.read_text())

    report_id = _make_report(client, cleanup, week_of="2026-07-06")
    post_a = _make_post(
        cleanup,
        corrected_text=ZH_A,
        final_translation=EN_A,
        xhs_note_id=f"exp-{uuid.uuid4().hex[:12]}",
    )
    post_b = _make_post(cleanup, caption_raw=ZH_B, machine_translation=EN_B)

    _add_block(client, report_id, {
        "section": "brand_watch", "block_type": "claim",
        "text_content": "Colorkey's lip mud line dominates matte-lip conversation.",
        "citations": [post_a, post_b],
    })
    trend = _add_block(client, report_id, {
        "section": "trend_radar", "block_type": "trend",
        "trend_title": "Lip mud goes matte",
        "text_content": "Matte lip mud is consolidating as the default texture.",
        "crossover": _CROSSOVER, "crossover_verdict": "watch",
        "citations": [post_b],
    })
    _add_block(client, report_id, {
        "section": "trend_radar", "block_type": "claim",
        "text_content": "Joocyee's lip mud drives the conversation.",
        "parent_block_id": trend["id"], "citations": [post_a],
    })
    _add_block(client, report_id, {
        "section": "not_crossing", "block_type": "claim",
        "text_content": "Jelly-texture blush will not cross this cycle.",
        "citations": [post_b],
    })
    return {"report_id": report_id, "post_a": post_a, "post_b": post_b}


def _export(client, report_id, variant=None) -> str:
    url = f"/api/reports/{report_id}/export"
    if variant:
        url += f"?variant={variant}"
    response = client.get(url)
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Section order, cover, markers, appendix
# ---------------------------------------------------------------------------


def test_export_section_order_and_cover(client, full_report):
    html = _export(client, full_report["report_id"])
    assert html.startswith("<!doctype html>")
    assert "Export Test Weekly Report" in html
    assert "Week of 6 July 2026" in html  # formatted week_of

    positions = [
        html.index('id="section-brand_watch"'),
        html.index('id="section-trend_radar"'),
        html.index('id="section-not_crossing"'),
        html.index('id="section-decoder"'),
        html.index('id="evidence"'),
    ]
    assert positions == sorted(positions)  # locked template IA order
    for title in ("C-beauty Brand Watch", "Trend Radar", "Not Crossing",
                  "Consumer Language Decoder", "Evidence"):
        assert title in html
    # seen_in_china has no blocks: omitted entirely
    assert 'id="section-seen_in_china"' not in html
    assert "Seen in China" not in html
    # self-contained: no external requests
    assert "http://" not in html and "https://" not in html
    assert "@media print" in html and "@page" in html


def test_export_markers_anchor_1to1_and_dedupe_by_post(client, full_report):
    html = _export(client, full_report["report_id"])
    marker_refs = re.findall(r'<sup class="cite">.*?</sup>', html)
    assert marker_refs  # superscript markers exist
    hrefs = re.findall(r'href="#src-(\d+)"', html)
    anchor_ids = re.findall(r'id="src-(\d+)"', html)
    # every marker resolves to an appendix anchor, every anchor is referenced
    assert set(hrefs) == set(anchor_ids)
    # appendix entries are unique posts, numbered sequentially from 1
    assert sorted(int(n) for n in anchor_ids) == [1, 2]
    # post_a is cited twice (brand_watch + nested trend claim): its number
    # appears in more than one marker but has exactly ONE appendix entry
    assert hrefs.count("1") >= 2
    # consecutive markers comma-separated (brand_watch claim cites 1,2)
    assert re.search(r'</a>,<a href="#src-', html)


def test_export_preserves_chinese_and_appendix_metadata(client, full_report):
    html = _export(client, full_report["report_id"])
    assert ZH_A in html and ZH_B in html  # source Chinese never stripped
    # apostrophes are HTML-escaped by autoescaping; compare escaped text
    assert str(escape(EN_A)) in html and str(escape(EN_B)) in html
    # zh blockquote comes BEFORE the en paragraph within the appendix entry
    entry = html[html.index('id="src-'):]
    assert entry.index('<blockquote class="zh">') < entry.index('<p class="en">')
    assert "Captured" in html  # capture date rendered
    # note id rendered when present
    with Session(get_engine()) as session:
        note_id = session.get(Post, uuid.UUID(full_report["post_a"])).xhs_note_id
    assert f"XHS note {note_id}" in html


def test_export_trend_crossover_table_verdict_and_decoder(client, full_report):
    html = _export(client, full_report["report_id"])
    assert "Lip mud goes matte" in html
    assert "Crossover Screen" in html
    for label in ("Visual legibility", "Price &amp; shipability",
                  "Creator translatability", "Institutional carrier"):
        assert label in html
    assert _CROSSOVER["visual_legibility"] in html
    assert 'class="pill pill-watch"' in html and ">Watch</span>" in html
    # nested claim rendered indented under the trend
    assert '<div class="trend-claims">' in html
    assert "Joocyee&#39;s lip mud drives the conversation." in html
    # decoder rendered from the glossary seed
    assert "避雷" in html and "mine warning" in html


# ---------------------------------------------------------------------------
# Empty sections / seen_in_china presence
# ---------------------------------------------------------------------------


def test_export_empty_sections_and_seen_in_china_present_when_filled(client, cleanup):
    report_id = _make_report(client, cleanup, title="Sparse report")
    post_id = _make_post(cleanup, caption_raw="上海线下快闪店里看到了 Rhode")

    html = _export(client, report_id)
    # all block sections empty -> subtle placeholder; seen_in_china omitted
    assert html.count("No entries this week.") == 3
    assert 'id="section-seen_in_china"' not in html

    _add_block(client, report_id, {
        "section": "seen_in_china", "block_type": "claim",
        "text_content": "Rhode is appearing in Shanghai offline pop-ups.",
        "citations": [post_id],
    })
    html = _export(client, report_id)
    assert 'id="section-seen_in_china"' in html
    assert "Seen in China" in html
    assert html.count("No entries this week.") == 3  # the other three, still


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def test_export_variant_differences_exactly_per_contract(client, full_report):
    report_id = full_report["report_id"]
    default = _export(client, report_id)
    deliverable = _export(client, report_id, "deliverable")
    public = _export(client, report_id, "public")

    assert default == deliverable  # deliverable is the default variant

    assert "Prepared by RedThread — confidential" in deliverable
    assert "Published with RedThread" not in deliverable
    assert 'rel="footnote"' not in deliverable

    assert "Published with RedThread" in public
    assert "confidential" not in public.lower()  # word omitted entirely
    assert 'rel="footnote"' in public  # rel metadata on citation anchors
    assert '<meta name="generator" content="RedThread">' in public

    # markers anchor to the appendix in BOTH variants
    for html in (deliverable, public):
        assert 'href="#src-1"' in html and 'id="src-1"' in html

    response = client.get(f"/api/reports/{report_id}/export?variant=bogus")
    assert response.status_code == 400


def test_export_404_and_auth(app, client):
    ghost = uuid.uuid4()
    assert client.get(f"/api/reports/{ghost}/export").status_code == 404
    assert client.get(f"/api/reports/{ghost}/export.pdf").status_code == 404
    anonymous = app.test_client()
    assert anonymous.get(f"/api/reports/{ghost}/export").status_code == 401
    assert anonymous.get(f"/api/reports/{ghost}/export.pdf").status_code == 401


# ---------------------------------------------------------------------------
# PDF smoke (the one test that needs Chromium; skips when unavailable)
# ---------------------------------------------------------------------------


def test_export_pdf_smoke(client, full_report):
    response = client.get(f"/api/reports/{full_report['report_id']}/export.pdf")
    if response.status_code == 503:
        pytest.skip(
            "chromium unavailable in test container: "
            + response.get_json()["error"]
        )
    assert response.status_code == 200
    assert response.content_type == "application/pdf"
    assert response.data.startswith(b"%PDF")
    disposition = response.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "export-test-weekly-report.pdf" in disposition
