# Verification 007 — M7 Export

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M7
Built via dynamic workflow wf_f28ba3c4-f03 (export-server + export-preview
parallel + fresh-context verifier). Verifier: all checks PASS, zero skips.

## What was tested

1. **Full suite** — **182 passed, 0 skipped** (174 + 8 export tests; the PDF
   smoke rendered a real PDF inside the container — chromium present).
2. **Client build** — exit 0. All five screens now exist; the Placeholder
   component is deleted (no sixth-screen drift possible via leftovers).
3. **Live deliverable HTML** — real fixture (2 posts with Chinese
   corrected_text + English final_translation, brand_watch claim, trend with
   full Crossover Screen + nested claim, not_crossing claim): section order
   1→4 correct with seen_in_china entirely absent when empty; decoder table
   rendered from the 12-term glossary; superscript markers on all three
   claims; **appendix dedupes repeat citations** (post cited twice → one
   Evidence entry, number reused); zh blockquote before en in every entry;
   capture date rendered; confidential footer.
4. **Public variant** — footer swap, zero occurrences of "confidential",
   rel="footnote" + generator meta added; anchors intact. Exactly the
   contract diffs, nothing else.
5. **PDF** — HTTP 200, application/pdf, `%PDF` magic, 67,284 bytes,
   Content-Disposition attachment with slugified title.
6. **Marker/anchor integrity** — every marker number has exactly one matching
   `id="src-N"` anchor.
7. **Print CSS** — @page A4 margins, @media print block with break rules,
   CJK font fallback stack present.
8. **Auth** — both export endpoints 401 without session; 404 unknown report.

## Notes

- Citation numbering logic lives ONLY in app/export/queries.py (single
  source; the template consumes prepared data).
- One template, two variants now (deliverable PDF + public HTML); the
  client-portal third output reuses the same renderer later by design.
- api image grew by chromium (~400 MB) — accepted cost of the locked
  Playwright export path.

## What changed

server/app/export/ (queries, template, pdf), routes/export.py, requirements
(+playwright), Dockerfile (chromium), tests/test_export.py; client
ExportPreview.jsx + apiText helper; Placeholder deleted.
