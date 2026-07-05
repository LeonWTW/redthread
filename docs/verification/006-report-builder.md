# Verification 006 — M6 Report Builder (Citation-Enforced)

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M6
Built via dynamic workflow wf_5c89cb09-06a (reports-api + report-editor
parallel + fresh-context verifier). Verifier: 7/7 PASS.

## What was tested

1. **Full suite** — **174 passed** (163 + 11: reports CRUD, section grouping,
   trend nesting/cascade, citation-set replace, every 400 validation path,
   raw-SQLAlchemy deferred-trigger backstop test asserting the iron-law
   message, DELETE-cited-post 409 regression guard, glossary endpoint).
2. **Client build** — exit 0 (compose client service = canonical node env).
3. **Live citation enforcement, all three layers**:
   - API: claim without citations → 400 "requires at least one citation
     (iron law #5)"; PATCH citations to [] → 400.
   - FK: DELETE cited post → 409 naming the report.
   - DB backstop: raw psql INSERT of an uncited claim → COMMIT **aborted** by
     trg_claim_requires_citation, row count 0 after rollback.
4. **Live trend flow** — trend block with full Crossover Screen (4 factors +
   verdict) in trend_radar → 201; nested claim under it appears in children;
   trend outside trend_radar → 400; decoder blocks rejected with the
   glossary-rendering explanation.
5. **Glossary endpoint** — 12 terms, term_zh-ordered, Chinese intact.
6. **Editor code audit (line evidence)** — save disabled until text + ≥1
   citation; citation chips open the source side panel (GET /api/posts/<id>);
   Library and the editor share one localStorage citation-tray module
   (key `redthread.citationTray`); inline /api/search attach path present.
7. **Scope** — owned files only; manifests untouched.

## Design notes

- The editor mirrors server rules for UX speed, but enforcement lives
  server-side + in the DB (client holds no correctness-critical logic).
- Library "Add to report" → citation tray (localStorage) → editor attach;
  no schema change needed and the evidence loop (chip → side panel) keeps
  verification one click away while writing.

## What changed

routes/reports.py (+ registration); tests/test_reports.py; client
Reports.jsx, ReportEditor.jsx, citationTray.js, Library wiring, styles.
