# Verification 000 — M0 Scaffold

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M0

## What was tested

1. **schema.sql applies cleanly to a fresh PostgreSQL 16** — via Docker Compose
   first boot (`/docker-entrypoint-initdb.d`).
   - Expected: all tables, enums, triggers created without error.
   - Actual: 7 tables (posts, post_images, annotations, glossary, reports,
     report_blocks, report_citations), 11 enums, both citation constraint
     triggers present. PASS.

2. **Iron law #5 enforced at the DB layer** — live psql transaction tests:
   - Claim block inserted without citation → COMMIT rejected:
     `ERROR: claim block ... has no citation; uncited claims are structurally
     forbidden (iron law #5)`. PASS.
   - Claim block + citation in one transaction → COMMIT succeeds. PASS.
   - `DELETE` of a cited post → blocked by FK `ON DELETE RESTRICT`
     (`report_citations_post_id_fkey`). PASS.

3. **pytest wiring** — `pytest -q` in a python:3.12-slim container against
   `server/`:
   - Expected: green run.
   - Actual: `1 passed in 0.05s`, exit 0. PASS.
   - Note: initial run failed collection (`ModuleNotFoundError: app`); fixed by
     adding `server/conftest.py` so pytest puts the server root on sys.path.

4. **Compose infra services** — `docker compose up -d postgres redis qdrant`:
   all three started; postgres healthcheck passed (schema checks above ran
   through `docker compose exec`). PASS.

## Not yet verified

- `api` / `worker` / `client` containers not built in M0 (only skeleton code
  exists); full-stack compose-up is an M1 acceptance criterion.
- backup.sh is intentionally a failing skeleton until M2 (exits 1 with an
  explanatory message so it can never silently pretend to have run).

## What changed

Everything — initial scaffold. See the M0 commits.
