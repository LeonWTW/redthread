# Verification 005 — M5 Library + Semantic Search + Golden-Set Eval Harness

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M5
Built via dynamic workflow wf_2a14ae6e-421 (search-server / library-client /
eval-harness parallel + fresh-context verifier). Verifier: 6/6 PASS.

## What was tested

1. **Full suite** — **163 passed** (125 + 38 new across search/delete and eval
   harness). Search tests run against LIVE Qdrant with deterministic vectors
   (score ordering, card shape parity with Inbox, Chinese preserved, ghost
   Qdrant points skipped); delete tests cover cascade + media file removal +
   Qdrant point removal and the cited-post 409.
2. **Live mechanical search** — real PG row + real Qdrant point + scripted
   query vector through the Flask client: 200, hit found, score 1.0; cleanup
   verified.
3. **Live search error path** — invalid OpenAI key → **503** with "embedding
   provider not configured — check .env". Post-verification fable fix: other
   ProviderErrors (transient) on the query embed now also map to 503
   ("temporarily unavailable — try again") instead of 500; suite re-run green.
4. **Live RESTRICT delete** — post + report + claim + citation created in one
   transaction (deferred trigger); DELETE → **409 naming the report**; after
   citation removal → 204, no orphan Qdrant point. TRUST currency holds at
   the API layer, backed by the DB FK.
5. **Eval harness** — no-live run validates the golden structure (synthetic
   example with real rendered Chinese 这个防晒霜很好用) and provably makes zero
   provider calls; scoring math unit-tested (OCR char-similarity, translation
   token-F1 as a documented coarse proxy, entity P/R/F1 on (type, text_zh));
   cost table (USD/MTok, marked UPDATE ME) with per-post $0.05 ceiling
   PASS/OVER column. Live accuracy×cost table runs once Leon supplies keys +
   the real 20-post golden set (harness README documents the drop-in format).
6. **Scope** — package.json / requirements.txt untouched; MediaStore.delete
   was an orchestrator-authorized interface addition.

## Notes for M6

Library's "Add to report" button ships disabled with a tooltip; M6 wires it.

## What changed

routes/search.py (new), DELETE /api/posts/<id> + shared _post_card in
routes/posts.py, MediaStore.delete (+ LocalMediaStore impl), Library.jsx,
server/app/eval/harness.py + scripts/eval_providers.py wrapper,
tests/golden/ structure + synthetic example, 38 new tests.
