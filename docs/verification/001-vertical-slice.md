# Verification 001 — M1 Vertical Slice

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M1
Built via dynamic workflow wf_61ace8e2-c51 (1 foundation + 4 parallel
implementers + 1 fresh-context verifier), then fable-reviewed in the main loop.

## What was tested

1. **Full test suite** — `docker compose run --rm api pytest -q`
   - Expected: green. Actual: **61 passed** (models roundtrip + partial-unique
     index, auth login/logout/me, authenticated media incl. 401/404, provider
     error-taxonomy mapping across all four providers (46 tests, mocked SDKs,
     no network), media store traversal rejection + extension whitelist,
     end-to-end slice with fake providers: capture → OCR → translate →
     bilingual JSON; HEIC → 415 with friendly message; caption-only → OCR
     skipped + translation success; token-auth capture → 202). PASS.

2. **Client production build** — node:24-alpine, `npm run build`:
   exit 0, bundle 166 kB (54 kB gzip). PASS.

3. **Glossary seed idempotence** — applied twice; count 12 both times, zero
   errors. PASS.

4. **Live smoke** — compose api+worker up: `/healthz` ok; login with .env
   creds → 204 + cookie; `/api/me` → authenticated:true; unauthenticated
   `/media/nope.png` → **401**. PASS.

5. **Worker task registration** — `celery inspect registered` shows
   `pipeline.ocr_post`, `pipeline.translate_post`. PASS (after review fix, see
   below).

## Fable review findings (fixed in main loop)

- `celery_app.py` lacked `include=["app.pipeline.tasks"]` — the worker would
  boot with zero registered tasks. Fixed; verified via `celery inspect`.
- `routes/media.py`: a path-traversal request raised `ValueError` from the
  media store → HTTP 500. Now caught → 404 (indistinguishable from missing).

## Known limitation (flagged to Leon)

Live OCR/translation E2E with the real Anthropic provider is **not yet
demonstrated**: no `ANTHROPIC_API_KEY` was available in the environment; .env
carries a placeholder. The slice is verified end-to-end with fake providers +
all provider SDK error mappings unit-tested. When Leon adds the key, a real
screenshot upload exercises the identical path; a failed key produces
`config_error` status visible via GET /api/posts/<id> (by design).

## What changed

server/app/models.py; providers (anthropic_providers, openai_embedding,
media_local); routes (auth, media, capture, posts); pipeline/tasks.py +
celery include fix; client slice UI (Login/Capture/PostView + router);
server/seeds/glossary.sql (12 terms); 5 new test files.
