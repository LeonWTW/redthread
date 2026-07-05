# Verification 008 — M8 Hardening + Demo Path + Docs True-up

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M8
Built via dynamic workflow wf_cd71cf4f-0ef (demo-e2e + docs-trueup +
security-sweep parallel + verifier), fable adjudication + fixes in main loop.

## What was tested

1. **Full suite** — **183 passed** (182 + integrated demo-path E2E), re-run
   green after all security fixes below.
2. **Demo path** — one test walks the entire product loop with fakes:
   login → capture PNG → 4-step pipeline success → annotate (hotkey values) →
   semantic search finds the post (live Qdrant point) → report claim citing
   it → deliverable export contains claim + marker + Chinese appendix →
   real PDF smoke. Capture→fully-processed measured **0.22s** (live target
   ≤30s applies to real providers; mechanical path has ~29s headroom).
3. **README accuracy** — verifier executed the documented quickstart commands
   (glossary seed, test command, eval dry-run, capture curl with token):
   all work as written. Stale test count fixed (183).
4. **Security sweep** — 27 routes enumerated: auth coverage complete;
   secrets clean including full git history scan (0 matches); session config
   matches decision 11; traversal/SQLi/template-injection surfaces clean;
   token comparisons constant-time; Jinja2 autoescape on with |safe only on
   integer-built markers.

## Security findings — fable adjudication

| # | Finding | Ruling |
|---|---------|--------|
| 1 | SECRET_KEY insecure fallback (medium) | **Fixed**: app refuses to boot without FLASK_SECRET_KEY outside tests. |
| 3 | POSTGRES_PASSWORD default (medium) | **Fixed locally**: rotated via ALTER USER + .env; VPS requirement documented in runbook checklist. |
| 6 | Rate limiter per-process memory (low) | **Fixed**: Redis-backed via REDIS_URL. |
| 8 | Media nosniff (low) | **Fixed**: X-Content-Type-Options header added. |
| 9 | MAX_CONTENT_LENGTH comment (low) | **Fixed**: comment corrected (per-request; sequential uploader makes it per-file). |
| 5 | No .dockerignore (low) | **Fixed**: server/.dockerignore (.env defensively excluded, caches/tests out of image). |
| 4 | API_TOKEN scope beyond /api/capture (low) | **Adjudicated intentional**: token covers the capture FLOW (capture/append/process/retry) so machine clients can finish multi-image submissions; security.py docstring now says so. |
| 2 | Root containers + Chromium --no-sandbox (medium) | **Deferred to VPS deploy** with rationale: localhost-bound dev; tracked in runbook pre-VPS checklist. |
| 10 | Outdated deps (low) | **Deferred**: refresh scheduled in pre-VPS checklist (pillow/anthropic first). |
| 7, 11, 12 | CSRF-by-Lax, CSV formula, unauthenticated infra | **Accepted for v1**: single analyst, same-origin app, infra localhost-only/no host ports. |

Verifier's two "verbatim text" flags ruled non-issues: architecture.md never
carried the positioning sentence (the lock forbids rephrasing, it does not
mandate inclusion); README's compliance line matches the Leon-approved
Sprint 1 formulation ("Content in the system is manually curated…").

## Incident during password rotation

Container recreate corrupted volume-mounted `__pycache__` (.pyc "marshal data
too short" → gunicorn boot loop). Cleared caches, restarted, verified healthz
+ full suite. server/.dockerignore now keeps caches out of images; runbook
already tells operators to restart after code changes.

## Remaining before daily use (all on Leon)

Real ANTHROPIC_API_KEY + valid OPENAI_API_KEY → run golden-set eval live;
VPS deploy per runbook checklist; B2 backup activation + drill (the clipping
gate); dogfood-week metrics (report ≤1h, capture+annotate ≤30s, pipeline
≥90% first-pass, search 4/5) to be recorded here during dogfood.
