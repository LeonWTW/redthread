# AI Contribution Log

Three lines per working session: date / what AI did / what Leon decided.

## 2026-07-05
- AI: Sprint 2 kickoff — understanding replay, 18-item ambiguity audit, wrote approved plan docs/plans/001-mvp-plan.md, applied authorized CLAUDE.md platform-column amendment + doc wording fixes, built M0 scaffold (schema.sql DDL, Docker Compose, env template, subagent definitions, backup skeleton).
- AI: M1 vertical slice via dynamic workflow (models, providers, auth/media/capture routes, OCR→translate chain, bilingual display, glossary seed; 61 tests + live smoke); fable review fixed celery task registration + media traversal handling.
- AI: M2 via dynamic workflow — URL-paste dedup (xhs.py), pHash near-dup soft warnings, CSV import, sequential mobile upload page, real backup.sh + restore_drill.sh (drill PASS on local restic repo), watchlist seed; 96 tests green.
- AI: M5–M8 via dynamic workflows — semantic search + Library + golden-set eval harness (M5), citation-enforced report builder with three-layer enforcement (M6), Jinja2 + Playwright/Chromium export in two variants (M7), hardening + docs true-up (README rewrite, architecture as-built, this log) (M8); suite at 182 passed.
- Leon: answered all 18 audit items (see docs/decisions.md), authorized the platform-column amendment, approved plan 001, ruled the sprint deadline untracked, pinned bilingual-concat embedding input, authorized autonomous dynamic-workflow execution.

## 2026-07-06
- AI: brought the stack up for Leon's first trial (env-controlled COOKIE_SECURE flag for plain-http Safari), verified the live pipeline end-to-end with real API keys, and delivered a full Cantonese user tutorial + test cases.
- AI: plan 003 UI redesign — wrote tokens.css + rewrote app.css as the "Editorial Intelligence" design system, drew the thread-stitch R logo (inline SVG + favicon), rebuilt Nav/Login, dispatched two implementer agents for per-page JSX classes, fixed an input-specificity bug and a drop-zone guard found in Playwright screenshot QA (12 shots, 2 rounds), verification notes 009.
- Leon: reported the UI as too crude and requested a premium-minimal redesign with animations and a logo; chose Editorial Intelligence direction, thread-stitch R mark, and ruled the export deliverable untouched; approved plan 003.
