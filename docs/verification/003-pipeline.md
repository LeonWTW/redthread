# Verification 003 — M3 Full Pipeline + Inbox

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M3 · Design: docs/plans/002
Built via dynamic workflow wf_d749bea8-bcc (pipeline-server + inbox-client
parallel + fresh-context verifier), fable adjudication + fix in main loop.

## What was tested

1. **Full test suite** — **111 passed** (96 + 15 new: full-chain end-to-end
   with fakes; skip-on-success proves providers NOT re-called; force cascade
   retry/translate re-runs translate+extract+embed but not OCR; PATCH
   corrected_text → forced re-embed while PATCH entities alone does not;
   transient extraction failure exhausts 3 attempts → failed/transient, chain
   stops, embed never called; live Qdrant round-trip for vectors.py; GET list
   shape/ordering). Re-run after the main-loop retry-reset fix: still 111. PASS.

2. **Client build** — exit 0 (182 kB / 59 kB gzip); Inbox with status badges,
   per-step retry, config_error non-retryable hint, polling, pagination. PASS.

3. **Live error taxonomy** — caption-only capture with placeholder Anthropic
   key: ocr=skipped, translate=failed/config_error with the provider's 401
   surfaced in error_message; extract/embed stayed pending (chain stopped). PASS.

4. **Live retry cascade** — retry/translate re-enqueued translate..embed;
   chain stopped at the still-failing step; extract never ran. PASS (see
   adjudication below for the stale-badge finding).

5. **Design-note conformance spot checks** — verifier matched note 002 §force
   and §embed-document/Qdrant clauses to tasks.py/vectors.py line-by-line. PASS.

## Verifier finding + fable adjudication

Retrying a step left **downstream steps showing stale statuses** from earlier
attempts (the design note did not require a reset). Ruled: the retry endpoint
now resets step..embed to `pending` + clears their error taxonomy in the same
transaction that enqueues the forced chain (design note 002 addendum).
Implemented, suite re-run green.

## Environment-blocked (NOT code defects — action Leon)

- **OPENAI_API_KEY in .env is invalid** (verifier curl'd api.openai.com
  directly: 401 invalid_api_key; container env byte-identical to .env). Live
  embedding + live Qdrant point proof therefore blocked; embed correctly
  recorded config_error. Needs a working key from Leon.
- ANTHROPIC_API_KEY still placeholder (known since M1).
Both code paths are covered by fakes + live config_error evidence.

## What changed

tasks.py → 4-step chain with (post_id, force) semantics; app/vectors.py
(Qdrant wrapper, upsert by post UUID); routes/posts.py → retry/<step> (with
pending-reset), PATCH corrections → re-embed, PATCH per-image corrected_ocr,
GET /api/posts list; Inbox screen + Nav + placeholder routes + PostView
retry/entities; design note 002 (+addendum).
