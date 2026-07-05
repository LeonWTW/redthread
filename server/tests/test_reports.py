"""M6 tasks 6.1/6.4 tests: report builder API + glossary read route.

Iron law #5 is exercised at BOTH layers: the API returns clear 400s before any
insert, and the deferred DB constraint trigger is proven separately with a raw
SQLAlchemy insert (the backstop, not the error path). Every test cleans up the
DB rows it creates; glossary seed rows are canonical data and stay.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import create_app
from app.db import get_engine
from app.models import Post, PostImage, Report, ReportBlock, ReportCitation

SEED_SQL = Path(__file__).resolve().parents[1] / "seeds" / "glossary.sql"

ZH_TEXT = "唇泥质地测试：珂拉琪的雾面唇泥非常显色，但是容易拔干，建议叠加润唇膏使用，整体瑕不掩瑜，回购意愿高。"
EN_TEXT = (
    "Lip mud texture test: Colorkey's matte lip mud is very pigmented but "
    "drying; layer a lip balm underneath."
)


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
            session.query(Report).filter(
                Report.id == uuid.UUID(report_id)
            ).delete(synchronize_session=False)
        session.commit()
    with Session(get_engine()) as session:
        for post_id in created["posts"]:
            post = session.get(Post, uuid.UUID(post_id))
            if post is not None:
                session.delete(post)
        session.commit()


def _make_post(cleanup, *, corrected_text=None, full_ocr_text=None, caption_raw=None,
               machine_translation=None, final_translation=None,
               image_path=None) -> str:
    with Session(get_engine()) as session:
        post = Post(
            corrected_text=corrected_text,
            full_ocr_text=full_ocr_text,
            caption_raw=caption_raw,
            machine_translation=machine_translation,
            final_translation=final_translation,
        )
        session.add(post)
        session.flush()
        if image_path is not None:
            session.add(PostImage(post_id=post.id, file_path=image_path))
        session.commit()
        post_id = str(post.id)
    cleanup["posts"].append(post_id)
    return post_id


def _make_report(client, cleanup, title="Test Weekly Report", **extra) -> str:
    response = client.post("/api/reports", json={"title": title, **extra})
    assert response.status_code == 201
    report_id = response.get_json()["id"]
    cleanup["reports"].append(report_id)
    return report_id


_CROSSOVER = {
    "visual_legibility": "High: the lip-mud finish reads instantly on camera.",
    "price_shipability": "Under $15 and lightweight; easy to ship.",
    "creator_translatability": "Western creators can replicate the swatch format.",
    "institutional_carrier": "No retail carrier yet; DTC only.",
}


# ---------------------------------------------------------------------------
# Create report -> claim with citations -> section grouping + snippets
# ---------------------------------------------------------------------------


def test_create_report_add_claim_and_get_sections_with_snippets(client, cleanup):
    report_id = _make_report(client, cleanup, week_of="2026-07-06")
    post_a = _make_post(
        cleanup, corrected_text=ZH_TEXT, final_translation=EN_TEXT,
        image_path="2026/07/report-test-a.png",
    )
    post_b = _make_post(
        cleanup, caption_raw="种草了花知晓的新腮红", machine_translation="Planted on Flower Knows' new blush",
    )

    response = client.post(
        f"/api/reports/{report_id}/blocks",
        json={
            "section": "brand_watch",
            "block_type": "claim",
            "text_content": "Colorkey's lip mud line dominates matte-lip conversation.",
            "citations": [post_a, post_b],
        },
    )
    assert response.status_code == 201
    block = response.get_json()
    assert block["section"] == "brand_watch"
    assert block["block_type"] == "claim"
    assert [c["post_id"] for c in block["citations"]] == [post_a, post_b]

    chip_a = block["citations"][0]
    assert chip_a["zh_snippet"] == ZH_TEXT[:80]  # source Chinese preserved
    assert "唇泥" in chip_a["zh_snippet"]
    assert chip_a["en_snippet"] == EN_TEXT[:80]
    assert chip_a["first_image_url"] == "/media/2026/07/report-test-a.png"

    chip_b = block["citations"][1]
    assert chip_b["zh_snippet"] == "种草了花知晓的新腮红"  # caption fallback
    assert chip_b["en_snippet"] == "Planted on Flower Knows' new blush"
    assert chip_b["first_image_url"] is None

    body = client.get(f"/api/reports/{report_id}").get_json()
    assert body["week_of"] == "2026-07-06"
    assert body["status"] == "draft"
    assert set(body["sections"]) == {
        "brand_watch", "trend_radar", "not_crossing", "seen_in_china"
    }  # decoder renders from the glossary; it carries no blocks
    assert [b["id"] for b in body["sections"]["brand_watch"]] == [block["id"]]
    assert body["sections"]["brand_watch"][0]["citations"][0]["zh_snippet"] == ZH_TEXT[:80]


# ---------------------------------------------------------------------------
# Iron law #5: API layer + DB backstop
# ---------------------------------------------------------------------------


def test_claim_without_citations_400_at_api_layer(client, cleanup):
    report_id = _make_report(client, cleanup)
    for payload in (
        {"section": "brand_watch", "block_type": "claim", "text_content": "Uncited."},
        {"section": "brand_watch", "block_type": "claim", "text_content": "Uncited.",
         "citations": []},
    ):
        response = client.post(f"/api/reports/{report_id}/blocks", json=payload)
        assert response.status_code == 400
        assert "citation" in response.get_json()["error"]
    assert client.get(f"/api/reports/{report_id}").get_json()["sections"][
        "brand_watch"
    ] == []


def test_db_backstop_deferred_trigger_rejects_uncited_claim():
    """Raw insert bypassing the API: the deferred trigger aborts at COMMIT."""
    with Session(get_engine()) as session:
        report = Report(title="Backstop probe report")
        session.add(report)
        session.flush()
        session.add(
            ReportBlock(
                report_id=report.id,
                section="brand_watch",
                block_type="claim",
                text_content="An uncited claim that must never land.",
            )
        )
        with pytest.raises(DBAPIError) as excinfo:
            session.commit()  # deferred claim_requires_citation fires here
        message = str(excinfo.value)
        assert "iron law" in message and "citation" in message
        session.rollback()  # the report row rolled back with the claim
    with Session(get_engine()) as session:
        assert (
            session.query(Report).filter_by(title="Backstop probe report").count() == 0
        )


def test_claim_citing_nonexistent_post_400_names_the_id(client, cleanup):
    report_id = _make_report(client, cleanup)
    ghost = str(uuid.uuid4())
    response = client.post(
        f"/api/reports/{report_id}/blocks",
        json={"section": "brand_watch", "block_type": "claim",
              "text_content": "Cites a ghost.", "citations": [ghost]},
    )
    assert response.status_code == 400
    assert ghost in response.get_json()["error"]


# ---------------------------------------------------------------------------
# Section / trend / crossover validation
# ---------------------------------------------------------------------------


def test_block_validation_400s(client, cleanup):
    report_id = _make_report(client, cleanup)
    post_id = _make_post(cleanup, caption_raw="测试帖")

    cases = [
        # decoder never carries blocks (rendered from the glossary table)
        ({"section": "decoder", "block_type": "claim", "text_content": "x",
          "citations": [post_id]}, "decoder"),
        # trend outside trend_radar
        ({"section": "brand_watch", "block_type": "trend",
          "trend_title": "Lip mud"}, "trend_radar"),
        # trend without title
        ({"section": "trend_radar", "block_type": "trend"}, "trend_title"),
        # crossover with wrong keys
        ({"section": "trend_radar", "block_type": "trend", "trend_title": "Lip mud",
          "crossover": {"visual_legibility": "ok", "bogus_factor": "nope"}},
         "crossover"),
        # bad verdict
        ({"section": "trend_radar", "block_type": "trend", "trend_title": "Lip mud",
          "crossover": _CROSSOVER, "crossover_verdict": "maybe"},
         "crossover_verdict"),
    ]
    for payload, needle in cases:
        response = client.post(f"/api/reports/{report_id}/blocks", json=payload)
        assert response.status_code == 400, payload
        assert needle in response.get_json()["error"]


# ---------------------------------------------------------------------------
# Nested claims under a trend + cascade on trend delete
# ---------------------------------------------------------------------------


def test_nested_claim_under_trend_and_trend_delete_cascades(client, cleanup):
    report_id = _make_report(client, cleanup)
    post_id = _make_post(cleanup, caption_raw="酵色唇泥")

    trend = client.post(
        f"/api/reports/{report_id}/blocks",
        json={"section": "trend_radar", "block_type": "trend",
              "trend_title": "Lip mud goes matte",
              "crossover": _CROSSOVER, "crossover_verdict": "watch"},
    ).get_json()
    assert trend["crossover"] == _CROSSOVER
    assert trend["crossover_verdict"] == "watch"
    assert trend["children"] == []

    child = client.post(
        f"/api/reports/{report_id}/blocks",
        json={"section": "trend_radar", "block_type": "claim",
              "text_content": "Joocyee's lip mud drives the conversation.",
              "parent_block_id": trend["id"], "citations": [post_id]},
    ).get_json()
    assert child["parent_block_id"] == trend["id"]

    body = client.get(f"/api/reports/{report_id}").get_json()
    radar = body["sections"]["trend_radar"]
    assert [b["id"] for b in radar] == [trend["id"]]  # child is NOT top-level
    assert [c["id"] for c in radar[0]["children"]] == [child["id"]]

    assert client.delete(f"/api/blocks/{trend['id']}").status_code == 204
    with Session(get_engine()) as session:
        assert session.get(ReportBlock, uuid.UUID(trend["id"])) is None
        assert session.get(ReportBlock, uuid.UUID(child["id"])) is None  # cascade
        assert (
            session.query(ReportCitation)
            .filter(ReportCitation.block_id == uuid.UUID(child["id"]))
            .count()
            == 0
        )


# ---------------------------------------------------------------------------
# PATCH citations replace semantics
# ---------------------------------------------------------------------------


def test_patch_citations_replace_and_zero_citation_guard(client, cleanup):
    report_id = _make_report(client, cleanup)
    post_a = _make_post(cleanup, caption_raw="帖子甲")
    post_b = _make_post(cleanup, caption_raw="帖子乙")

    block = client.post(
        f"/api/reports/{report_id}/blocks",
        json={"section": "not_crossing", "block_type": "claim",
              "text_content": "This format will not cross.",
              "citations": [post_a, post_b]},
    ).get_json()
    assert len(block["citations"]) == 2

    # Replace 2 -> 1
    response = client.patch(
        f"/api/blocks/{block['id']}", json={"citations": [post_a]}
    )
    assert response.status_code == 200
    assert [c["post_id"] for c in response.get_json()["citations"]] == [post_a]

    # Replace -> 0 on a claim: 400 BEFORE touching the DB
    response = client.patch(f"/api/blocks/{block['id']}", json={"citations": []})
    assert response.status_code == 400
    assert "citation" in response.get_json()["error"]
    with Session(get_engine()) as session:
        rows = (
            session.query(ReportCitation)
            .filter(ReportCitation.block_id == uuid.UUID(block["id"]))
            .all()
        )
        assert [str(row.post_id) for row in rows] == [post_a]  # unchanged

    # Deleting the claim itself is fine: its citations cascade with the block.
    assert client.delete(f"/api/blocks/{block['id']}").status_code == 204
    with Session(get_engine()) as session:
        assert (
            session.query(ReportCitation)
            .filter(ReportCitation.block_id == uuid.UUID(block["id"]))
            .count()
            == 0
        )


# ---------------------------------------------------------------------------
# Regression guard: a cited post still cannot be deleted
# ---------------------------------------------------------------------------


def test_delete_cited_post_still_409(client, cleanup):
    report_id = _make_report(client, cleanup, title="Citing report (409 guard)")
    post_id = _make_post(cleanup, caption_raw="被引用的帖子")
    client.post(
        f"/api/reports/{report_id}/blocks",
        json={"section": "brand_watch", "block_type": "claim",
              "text_content": "Cited claim.", "citations": [post_id]},
    )
    response = client.delete(f"/api/posts/{post_id}")
    assert response.status_code == 409
    assert "Citing report (409 guard)" in response.get_json()["error"]
    with Session(get_engine()) as session:
        assert session.get(Post, uuid.UUID(post_id)) is not None  # survived


# ---------------------------------------------------------------------------
# Report list / patch / delete lifecycle
# ---------------------------------------------------------------------------


def test_report_list_ordering_block_count_status_and_delete_cascade(client, cleanup):
    report_1 = _make_report(client, cleanup, title="Older report")
    report_2 = _make_report(client, cleanup, title="Newer report")
    post_id = _make_post(cleanup, caption_raw="列表测试帖")
    block = client.post(
        f"/api/reports/{report_1}/blocks",
        json={"section": "seen_in_china", "block_type": "claim",
              "text_content": "Reverse-flow observation.", "citations": [post_id]},
    ).get_json()

    listing = client.get("/api/reports").get_json()["reports"]
    ours = [item for item in listing if item["id"] in (report_1, report_2)]
    assert [item["id"] for item in ours] == [report_2, report_1]  # newest first
    by_id = {item["id"]: item for item in ours}
    assert by_id[report_1]["block_count"] == 1
    assert by_id[report_2]["block_count"] == 0
    assert by_id[report_1]["status"] == "draft"

    # PATCH status draft -> final; bad status rejected
    response = client.patch(f"/api/reports/{report_1}", json={"status": "final"})
    assert response.status_code == 200
    assert response.get_json()["status"] == "final"
    assert client.patch(
        f"/api/reports/{report_1}", json={"status": "published"}
    ).status_code == 400

    # DELETE cascades blocks + citations; the cited post survives
    assert client.delete(f"/api/reports/{report_1}").status_code == 204
    with Session(get_engine()) as session:
        assert session.get(Report, uuid.UUID(report_1)) is None
        assert session.get(ReportBlock, uuid.UUID(block["id"])) is None
        assert (
            session.query(ReportCitation)
            .filter(ReportCitation.block_id == uuid.UUID(block["id"]))
            .count()
            == 0
        )
        assert session.get(Post, uuid.UUID(post_id)) is not None


def test_reports_require_session(app):
    anonymous = app.test_client()
    assert anonymous.get("/api/reports").status_code == 401
    assert anonymous.post("/api/reports", json={"title": "x"}).status_code == 401
    assert anonymous.get("/api/glossary").status_code == 401


# ---------------------------------------------------------------------------
# Glossary (Decoder preview)
# ---------------------------------------------------------------------------


def test_glossary_returns_seeded_terms_ordered(client):
    # The seed script is idempotent (ON CONFLICT DO NOTHING): safe to (re)apply.
    with get_engine().begin() as connection:
        connection.exec_driver_sql(SEED_SQL.read_text())

    body = client.get("/api/glossary").get_json()
    terms = body["terms"]
    assert len(terms) >= 12
    by_zh = {term["term_zh"]: term for term in terms}
    assert by_zh["避雷"]["term_en"] == "mine warning"
    assert by_zh["平替"]["term_en"] == "affordable dupe"
    assert set(terms[0]) == {"term_zh", "term_en", "note", "category"}
    zh_values = [term["term_zh"] for term in terms]
    assert zh_values == sorted(zh_values)  # ordered by term_zh
