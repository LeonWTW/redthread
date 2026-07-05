# RedThread

## Overview

RedThread is an internal intelligence-production platform that turns Xiaohongshu (小红书) beauty content into English strategic insights for Western beauty and wellness brands.

Xiaohongshu is the platform where Chinese beauty consumers research and decide what to buy, but its content is effectively unreadable for Western brand teams: it is in Chinese, lives inside a closed mobile app, and depends on cultural context (community slang, review conventions) that machine translation alone does not carry. A bilingual analyst can read it — but doing so at a useful scale is an operations problem: screenshots pile up on a phone, translations are ad hoc, nothing is searchable later, and assembling a weekly intelligence report takes hours with no reliable way to trace a claim back to its source post.

RedThread is the production line that fixes this. The analyst captures posts (screenshots, URLs, CSV batches); a processing pipeline runs OCR, translation, entity extraction, and embedding; the analyst reviews and annotates each post with a fixed taxonomy in a keyboard-first triage screen; everything lands in a searchable bilingual library; and a report builder assembles weekly reports in which every claim carries a citation that resolves to a captured source post.

A core design principle: the app is a factory, not the product. The weekly report is the product. The platform exists to make producing that report fast, verifiable, and repeatable by a single analyst.

## Current Status

Sprint 2 — the five-screen MVP is implemented (M0–M7 verified; see [docs/verification/](docs/verification/)):

- **Inbox** — pipeline status per post (OCR → translate → extract → embed), per-step retry, error surfacing.
- **Triage** — keyboard-first three-pane annotation screen (locked hotkey map, save-and-next).
- **Library** — semantic search over the bilingual corpus (Qdrant), result cards, add-to-report.
- **Report Editor** — outline with citation chips; uncited claims are rejected by the API and, as a backstop, by a database trigger.
- **Export Preview** — one Jinja2 template, two variants: confidential PDF deliverable (Playwright/Chromium) and public HTML.

Test suite: 183 passed. Pending before daily use: real AI provider API keys, deployment to the VPS, Backblaze B2 backup activation (blocking gate for daily clipping), and dogfood-week metrics (report ≤1h, capture+annotate ≤30s/post).

## Quickstart

Prerequisites: Docker with Compose.

```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY, FLASK_SECRET_KEY,
# ANALYST_USERNAME/ANALYST_PASSWORD, API_TOKEN, POSTGRES_PASSWORD
# (generation commands are in the .env.example comments).

docker compose up -d
```

`schema.sql` (the single source of truth for the database) is applied automatically on the first boot of the postgres container via `/docker-entrypoint-initdb.d`.

Seed the glossary (idempotent, safe to re-run):

```bash
docker compose exec -T postgres psql -U redthread -d redthread -v ON_ERROR_STOP=1 -f - < server/seeds/glossary.sql
```

Then:

- Client (Vite dev server): http://localhost:5173
- API: http://localhost:8000 (health check: `GET /healthz`)
- Log in with `ANALYST_USERNAME` / `ANALYST_PASSWORD` from `.env`. Single analyst account; no registration.

After editing server code: `docker compose restart api worker` (code is volume-mounted but loaded at process start).

### Tests

```bash
docker compose run --rm api pytest -q
```

### Provider eval harness (golden set)

Structure check without any provider calls (safe anywhere):

```bash
python3 scripts/eval_providers.py
```

Live accuracy × cost eval (requires real keys and the 20-post golden set under `tests/golden/posts/` — format documented in `tests/golden/README.md`):

```bash
python3 scripts/eval_providers.py --live --steps ocr,translation
```

### Backup and restore drill

```bash
./scripts/backup.sh          # nightly: pg_dump + restic snapshot of dumps + media volume
./scripts/restore_drill.sh   # monthly: restore latest snapshot into a scratch DB, verify, drop
```

Both read `RESTIC_REPOSITORY` / `RESTIC_PASSWORD` from `.env` and fail loudly when unset. Cron line, B2 configuration, and the drill log live in [docs/runbook.md](docs/runbook.md).

## Capture API

`POST /api/capture` accepts multipart form data — up to 20 files under `images`, plus optional `caption` and `url` fields. Machine clients authenticate with the long-lived `API_TOKEN` via header; browser clients use the session cookie.

```bash
curl -X POST http://localhost:8000/api/capture \
  -H "X-API-Token: $API_TOKEN" \
  -F "images=@screenshot.png" \
  -F "caption=optional caption text" \
  -F "url=https://www.xiaohongshu.com/explore/<note-id>"
```

A URL whose parsed note ID already exists returns `200 {"already_captured": true}` with the existing post ID; new captures return `202` and enqueue the pipeline. The capture API supports arbitrary authenticated clients.

## Project Documents

- [docs/project-vision.md](docs/project-vision.md)
- [docs/requirements.md](docs/requirements.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/decisions.md](docs/decisions.md) — running decision log
- [docs/runbook.md](docs/runbook.md) — backup, restore drill, service recovery
- [docs/watchlist.md](docs/watchlist.md) — daily-clipping brand watchlist
- [docs/plans/](docs/plans/) — approved implementation plans and design notes
- [docs/verification/](docs/verification/) — per-milestone verification notes (000–007)
- [docs/ai-log.md](docs/ai-log.md) — AI contribution log

## Setup Notes

- Single-command startup via Docker Compose (web client, API server, Celery worker, PostgreSQL, Redis, Qdrant). All ports bind to 127.0.0.1 in development.
- AI providers sit behind interfaces (`OCRProvider`, `TranslationProvider`, `ExtractionProvider`, `EmbeddingProvider`, `MediaStore`) and are selected via `.env`; defaults are Anthropic Haiku (vision OCR, translation, extraction) and OpenAI `text-embedding-3-small` (embedding).
- Media files live in a private Docker volume and are served only through an authenticated Flask route — never a public static directory.
- Secrets are supplied only through `.env` (git-ignored); `.env.example` documents every required variable.
- Content in the system is manually curated by the analyst for research and analysis purposes; the system does not perform automated bulk collection.
