# Plan 001 — RedThread MVP Implementation Plan (M0–M8)

- **Status:** APPROVED
- **Approval record:** Leon approved in chat, 2026-07-05 ("Plan approved"), authorizing autonomous execution via dynamic workflows. Leon additionally ruled the Sprint 2 calendar deadline is not tracked ("不用care about deadline"); recorded in docs/decisions.md.
- **Scope:** the complete five-screen MVP, built continuously in dependency order per CLAUDE.md §7.
- **Language rule:** all artifacts in English; chat with Leon in Cantonese.

---

## 1. Locked decisions from Sprint 2 kickoff (2026-07-05)

These were resolved in the kickoff Q&A and are binding for all milestones. They will also be recorded in `docs/decisions.md` (created in M0).

1. **Pipeline status:** four columns on `posts` (`ocr_status`, `translate_status`, `extract_status`, `embed_status`) sharing enum `step_status: pending | running | success | failed | skipped`, plus per-step `error_type` and `error_message`.
2. **Timestamps:** `TIMESTAMPTZ` (UTC) everywhere; `created_at`/`updated_at` on all tables; `posts.captured_at` is a distinct business fact (defaults to `now()`, CSV import may backfill).
3. **Indexes:** partial UNIQUE on `xhs_note_id WHERE xhs_note_id IS NOT NULL`; `captured_at DESC`; UNIQUE `annotations.post_id` (one annotation row per post); pHash stored as `BIGINT`, near-match via app-level Hamming full scan (no DB extension).
4. **Cascades:** `post_images`, `annotations` → `ON DELETE CASCADE`; `report_citations` → posts `ON DELETE RESTRICT` — a cited post cannot be deleted; Library delete surfaces "cited in report X".
5. **Media-less captures:** posts without images sit in an awaiting-media state; the pipeline starts on first image. If `caption_raw` exists but no images, OCR is `skipped` and translation runs on the caption. **CSV columns: `url, caption, captured_at, notes` — only `url` required.**
6. **Celery granularity:** one step = one Celery task per post; four tasks in a chain. The OCR task loops images and skips those with existing `raw_ocr`. Retrying step N re-enqueues N **and all downstream steps**. Transient errors auto-retry ×2 with backoff before `failed`.
7. **Qdrant:** single collection `posts`; point ID = post UUID; distance = cosine; payload = `{post_id}` only; re-embed = upsert on same point ID (idempotent). Filters happen in PostgreSQL after retrieval.
8. **Embedding default:** OpenAI `text-embedding-3-small`; BGE-M3 (self-hosted) as eval candidate. Decided before the corpus grows.
9. **Uploads:** 15 MB/file, ≤20 files/batch; accept PNG/JPEG/WebP. **HEIC is rejected** with an error message telling the analyst to upload a screenshot instead (no pillow-heif in v1; camera photos are a v2 concern).
10. **Mobile upload strategy:** sequential per-file upload with per-file progress and single-file retry — no monolithic multipart (iOS Safari kills long requests).
11. **Session cookie:** `HttpOnly` + `Secure` + `SameSite=Lax`; permanent session lifetime 30 days; SPA and API on the same origin (server-set cookies are not subject to Safari ITP's 7-day cap).
12. **Error taxonomy (per step):** `transient` (timeout/rate-limit/5xx — auto-retried), `provider_error` (4xx/refusal), `parse_error` (malformed model output), `config_error` (missing/invalid key — retry is futile and the UI says so), `storage_error`. Inbox shows status + error type + message per step; "Retry" = re-enqueue that step + downstream.
13. **Platform column (CLAUDE.md amendment, authorized by Leon 2026-07-05):** `posts.platform TEXT NOT NULL DEFAULT 'xhs'` — the only structural reservation for future expansion. CLAUDE.md §6 amended; architecture.md open question reworded; project-vision.md unchanged.
14. **Triage hotkeys (full map):** category 1–4; consumer_signal Q–T; trend_type A/S/D/F/G/H; recommended_action 7/8/9/0; origin Z/X/C/V (optional, skip = NULL); Enter save-and-next; Backspace skip.
15. **Entity extraction schema:** types `brand | product | ingredient | other`; each entity `{text_zh, text_en, type, confidence}`; stored as JSONB on posts. Confidence is a model self-reported heuristic, not a calibrated probability; displayed for entities only — never for OCR or translation.
16. **M0 housekeeping:** move `Srpint1/README.md` → repo root, other three docs → `docs/`; fix README links; `git init`; private GitHub repo `redthread` via SSH; invite collaborator `pcolbert-uo`.
17. **Providers & infra:** Anthropic Haiku vision for OCR, Haiku for translation/extraction; OpenAI `text-embedding-3-small` for embedding (keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Backups to **Backblaze B2** (`B2_KEY_ID` / `B2_APP_KEY` / `B2_BUCKET` placeholders in `.env.example`). Deployment: Leon's existing Hetzner VPS (Docker Compose); dev on Mac. M2 backup script targets VPS → B2.
18. **Sprint 2 deadline:** **STILL UNANSWERED** — Leon's reply left the date blank. Must be provided at plan approval and recorded in `docs/decisions.md`.

### Embedding input (pinned per Leon's request)

**Decision: bilingual concatenation.** The embedded document is:

```
{corrected_text if present else full_ocr_text}
\n---\n
{final_translation if present else machine_translation}
```

If the post has a caption, it is part of the zh aggregate (it already feeds `full_ocr_text` aggregation).

**Reasons:** (a) real queries are mixed Chinese/English, and a bilingual document gives the vector surface forms in both languages, improving recall for both query languages with a multilingual model; (b) it is correction-consistent — either a zh correction or an en correction changes the embedded document, so the iron-law re-embed trigger covers both; (c) one vector per post is preserved (no dual-vector complexity). Ceiling check: `text-embedding-3-small` cost is negligible (~$0.02/1M tokens); doubling input length is immaterial.

---

## 2. Model routing summary

- **[fable]** — main loop only: DDL, provider interface contracts, idempotency/retry semantics, citation-enforcement design, auth design, eval conclusions, every plan/review gate. Each [fable] task below carries a one-line justification.
- **[sonnet]** — dispatched to `implementer` subagent: routes, tasks, components, tests, Docker config.
- **[haiku]** — dispatched to `mechanic` subagent: boilerplate from an established pattern, fixtures, docs appends, `.env.example`, lint/format.
- Escalation: one failed review → escalate one tier; never retry the same tier twice.
- Tightly-coupled multi-file edits needing shared live context stay in the main loop even if [sonnet]-shaped.

---

## 3. Milestones

### M0 — Scaffold

| # | Task | Model |
|---|------|-------|
| 0.1 | `git init`; move `Srpint1/README.md` → root, three docs → `docs/`, fix links, remove `Srpint1/` and `.bak` files once git history protects them | [haiku] |
| 0.2 | Repo layout: `server/`, `client/`, `docker-compose.yml` (flask-api, celery-worker, postgres, redis, qdrant, client), pytest wiring, `.gitignore` | [sonnet] |
| 0.3 | **`schema.sql` full DDL** — all tables (posts, post_images, annotations, glossary, reports, report_blocks, report_citations), enums, indexes, cascade rules per locked decisions | [fable] — DDL is the single most expensive artifact to reverse (iron-law territory) |
| 0.4 | `.env.example` — every variable: `POSTGRES_*`, `REDIS_URL`, `QDRANT_URL`, `FLASK_SECRET_KEY`, `ANALYST_USERNAME`, `ANALYST_PASSWORD`, `API_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, `MEDIA_ROOT` | [haiku] |
| 0.5 | `.claude/agents/implementer.md` (sonnet) + `mechanic.md` (haiku) with tool lists per CLAUDE.md §4 | [haiku] |
| 0.6 | `scripts/backup.sh` skeleton + `docs/runbook.md` stub (restore-drill placeholder) | [haiku] |
| 0.7 | `docs/decisions.md` (kickoff decisions + Sprint 2 deadline), `docs/ai-log.md` first entry, `docs/verification/` dir | [haiku] |
| 0.8 | Create private GitHub repo `redthread` (SSH remote), invite `pcolbert-uo`, first commits, `sprint-2-prototype` branch | main loop (needs Leon's gh auth; mechanical but credential-bound) |

**Acceptance criteria:** `docker compose up` brings all services healthy; `schema.sql` applies cleanly to a fresh PostgreSQL; `pytest` runs green (zero tests is fine); repo private on GitHub with collaborator invited; docs in final locations with working links.

**Verification notes plan** (`docs/verification/000-scaffold.md`): compose up output; `psql -f schema.sql` exit code; pytest output; screenshot/URL of repo settings.

**Runtime cost impact:** none (no API calls).

### M1 — Vertical slice (iron law #1)

One image in → OCR → translation → persist → bilingual side-by-side display.

| # | Task | Model |
|---|------|-------|
| 1.1 | **Provider interface contracts**: `OCRProvider`, `TranslationProvider`, `ExtractionProvider`, `EmbeddingProvider`, `MediaStore` — method signatures, typed error hierarchy (maps to the 5-value error taxonomy), config/env selection mechanism | [fable] — interface contracts lock every later provider implementation; wrong shape = rework across pipeline |
| 1.2 | Flask app factory + session auth (single analyst seeded from env; login rate-limited; session cookie per decision 11) + authenticated media route (`MediaStore` local-volume impl) | [sonnet] |
| 1.3 | SQLAlchemy models conforming to `schema.sql` (models follow DDL, never the reverse) | [sonnet] |
| 1.4 | `AnthropicOCRProvider` (Haiku vision) + `AnthropicTranslationProvider` (glossary injection, comment-section marker support) | [sonnet] |
| 1.5 | Minimal capture endpoint (single image) + 2-task Celery chain (OCR → translate) writing per-step status. Celery is used from the slice onward — no synchronous throwaway to rework in M3 | [sonnet] |
| 1.6 | React SPA scaffold (Vite) + slice display page: image, zh text, en translation side by side | [sonnet] |
| 1.7 | Glossary seed SQL (避雷, 平替, 成分党, 种草, 求真 + starter set) | [haiku] |
| 1.8 | Milestone review + verification notes | [fable] — review gate per CLAUDE.md §4 |

**Acceptance criteria:** upload one XHS screenshot in the browser → within ~60s the post page shows the image, Chinese OCR text, and English translation; both stored in PostgreSQL with `ocr_status = translate_status = success`; media served only through the authenticated route (direct URL without session → 401).

**Verification notes plan** (`001-vertical-slice.md`): end-to-end walkthrough with a real screenshot; DB row dump; unauthenticated media request → 401; glossary term visible in translation prompt log.

**Runtime cost impact:** ~$0.005/post (1-image OCR + translation on Haiku). Negligible against ceilings.

### M2 — Backup live + capture hardening (BLOCKING GATE before daily clipping)

| # | Task | Model |
|---|------|-------|
| 2.1 | `POST /api/capture` with `API_TOKEN` header auth: multi-image + caption + optional URL | [sonnet] |
| 2.2 | Mobile upload page: batch photo-picker/drag-drop, sequential per-file upload + progress + retry, 15 MB/20-file limits, HEIC rejection message | [sonnet] |
| 2.3 | URL paste + note-ID parse + dedup → friendly "already captured" | [sonnet] |
| 2.4 | CSV import (`url, caption, captured_at, notes`; url required) | [sonnet] |
| 2.5 | pHash on ingest + near-dup soft warning (app-level Hamming) | [sonnet] |
| 2.6 | Backup implementation: nightly `pg_dump` + media sync (restic) → Backblaze B2, cron on VPS; `docs/runbook.md` restore procedure + monthly drill schedule | [sonnet] |
| 2.7 | Backup review + **restore drill actually executed once** + milestone review | [fable] — data-loss protection is a blocking gate; a backup that never restored is not a backup |

**Acceptance criteria:** all four capture paths work; duplicate URL returns "already captured" without a second record; HEIC upload → clear rejection; backup ran on schedule ≥1 night on the VPS; one successful restore into a scratch database + media dir documented.

**Verification notes plan** (`002-capture-backup.md`): each capture path exercised; dedup and pHash-warning cases; B2 bucket listing; restore drill transcript.

**Runtime cost impact:** none new per post (pipeline unchanged); B2 storage cost is infra, not the $50 API budget (expected < $1/month at v1 volumes).

**Exit action:** tell Leon explicitly — **daily clipping starts NOW.** Quota 25/day = 10 watchlist + 10 category browse + 5 free explore. `docs/watchlist.md` seeded (task 2.8 [haiku]) with: Judydoll 橘朵, Florasis 花西子, Perfect Diary 完美日记, Colorkey 珂拉琪, INTO YOU, Joocyee 酵色, Flower Knows 花知晓 + labeled empty KOC slots.

### M3 — Full pipeline + Inbox

| # | Task | Model |
|---|------|-------|
| 3.1 | **Idempotency & retry semantics design note**: task signatures, status transitions, downstream invalidation on retry, transient auto-retry policy, error-taxonomy mapping | [fable] — iron law #3 logic; wrong semantics corrupt state silently |
| 3.2 | Celery chain extended to 4 steps (OCR → translate → extract → embed) implementing 3.1; per-step status + error writes | [sonnet] |
| 3.3 | `AnthropicExtractionProvider` (entity JSONB per decision 15) + `OpenAIEmbeddingProvider` + Qdrant upsert (bilingual-concat input per pinned decision) | [sonnet] |
| 3.4 | Correction endpoints: editing `corrected_text` / `final_translation` enqueues re-embed (iron law #2) | [sonnet] |
| 3.5 | Inbox screen: pipeline status table, per-step error surface (type + message), per-step retry button | [sonnet] |
| 3.6 | Dev fixtures/seed data | [haiku] |
| 3.7 | Milestone review + verification notes | [fable] — review gate |

**Acceptance criteria:** a captured post flows through all four steps to a Qdrant vector; killing a step mid-run and retrying does not duplicate data; retrying OCR re-runs downstream steps; a correction triggers exactly one re-embed; Inbox shows accurate per-step status and error categories; `config_error` renders as non-retryable guidance.

**Verification notes plan** (`003-pipeline.md`): idempotency test transcript (run step twice, diff DB state); forced-failure per error category; retry-cascade demonstration; Qdrant point count vs posts count.

**Runtime cost impact:** full per-post cost ≈ $0.01 (3-image OCR ~$0.006 + translate ~$0.003 + extract ~$0.002 + embed ~$0.00002) — 5× headroom under the $0.05 ceiling; 750 posts/month ≈ $7.5, well under $50/month.

### M4 — Triage screen

| # | Task | Model |
|---|------|-------|
| 4.1 | Three-pane layout: images | OCR + translation + entities (inline-editable; entity confidence badge) | annotation panel | [sonnet] |
| 4.2 | Full hotkey map (decision 14) + save-and-next + skip flow | [sonnet] |
| 4.3 | Annotation API (upsert single row per post; taxonomy enums enforced server-side) | [sonnet] |
| 4.4 | Milestone review incl. timed 30s-per-post walkthrough with Leon | [fable] — review gate; the 30s counter-metric is defended here |

**Acceptance criteria:** annotate a real post using only the keyboard in ≤30s; inline OCR/translation edits persist to `corrected_*`/`final_*` fields and enqueue re-embed; skipped origin stores NULL.

**Verification notes plan** (`004-triage.md`): stopwatch runs (5 posts); hotkey map test matrix; correction → re-embed evidence.

**Runtime cost impact:** corrections cause re-embeds (~$0.00002 each) — immaterial.

### M5 — Library + semantic search + golden-set eval

| # | Task | Model |
|---|------|-------|
| 5.1 | Search endpoint: embed query → Qdrant top-k → PostgreSQL join → bilingual cards | [sonnet] |
| 5.2 | Library UI: search box, result cards (bilingual + annotations), "add to report", manual delete (RESTRICT-aware error for cited posts) | [sonnet] |
| 5.3 | Golden-set harness: `tests/golden/` structure (20 posts, ground truth supplied by Leon), eval script reporting **accuracy × cost per provider** | [sonnet] |
| 5.4 | Eval run + provider conclusions (incl. PaddleOCR and BGE-M3 candidates if warranted) | [fable] — golden-set eval conclusions are named fable-only in CLAUDE.md §4 |
| 5.5 | Milestone review + verification notes | [fable] — review gate |

**Acceptance criteria:** the 4-of-5 representative-query relevance metric passes; zh, en, and mixed queries all return sane results; eval script outputs a table of accuracy and per-post cost per provider; deleting a cited post is blocked with a clear message.

**Verification notes plan** (`005-library-eval.md`): the 5 representative queries + top-5 screenshots; eval table; delete-blocked case.

**Runtime cost impact:** query embeds negligible; each full eval run over 20 posts ≈ $0.20–$0.50 depending on candidate set — budgeted, infrequent.

### M6 — Report builder (citation-enforced)

| # | Task | Model |
|---|------|-------|
| 6.1 | **Citation-enforcement design**: report/block/claim data model usage, server-side invariant (a claim cannot be persisted without ≥1 citation), Crossover Screen block as a trend-level template component | [fable] — iron law #5; structural impossibility must be designed, not patched |
| 6.2 | Report CRUD API implementing 6.1's invariant | [sonnet] |
| 6.3 | Report Editor UI: outline per §5 IA, citation chips, chip-click → source post side panel | [sonnet] |
| 6.4 | Consumer Language Decoder section rendered from glossary | [haiku] |
| 6.5 | Milestone review + verification notes | [fable] — review gate |

**Acceptance criteria:** attempting to save a claim without a citation fails at the API level (not just hidden in UI); every §5 section type is composable; Crossover Screen block carries four factors + verdict enum (`will_cross | wont_cross | watch`); citation chip opens the correct source post.

**Verification notes plan** (`006-report-builder.md`): API-level uncited-claim rejection (curl transcript); a full assembled sample report; side-panel navigation check.

**Runtime cost impact:** none (no new API usage).

### M7 — Export (the only thing a client ever sees — design effort lands here)

| # | Task | Model |
|---|------|-------|
| 7.1 | HTML report template: five IA sections, bilingual quote styling, citation rendering, print CSS | [sonnet] |
| 7.2 | Playwright PDF render path | [sonnet] |
| 7.3 | Public web variant (citations become internal links; same template, three outputs) | [sonnet] |
| 7.4 | Template quality review against real report content | [fable] — this is the client-facing product surface; the quality gate is a judgment call |

**Acceptance criteria:** one template renders PDF + public HTML from the same report; PDF is print-clean (no clipped sections, working page breaks); every claim visibly cited; source Chinese preserved alongside English throughout.

**Verification notes plan** (`007-export.md`): PDF attached; HTML variant link; visual checklist per section.

**Runtime cost impact:** none (Playwright is local).

### M8 — Hardening + dogfood support + demo path

| # | Task | Model |
|---|------|-------|
| 8.1 | Demo-path E2E: live-capture a post → processed into Library ≤30s → answer an English question with that post's citation → open a weekly report | [sonnet] |
| 8.2 | Dogfood-week fix rounds + final security pass (auth on all routes incl. media, rate limit, secrets audit) | [fable] — security review is fable-only per CLAUDE.md §4 |
| 8.3 | Docs true-up: README + architecture.md reflect reality; ai-log and verification notes complete | [haiku] |

**Acceptance criteria:** demo path executes cleanly end-to-end; all four §5 metrics measured during dogfood week and recorded; no secret in the repo (scan evidence); README quickstart works on a clean clone.

**Verification notes plan** (`008-hardening.md`): demo-path recording/transcript; metrics table; secret-scan output.

**Runtime cost impact:** dogfood month at 25 posts/day ≈ $7.5–$10/month total — final headroom confirmation against $50.

---

## 4. Dispatch-brief template (per CLAUDE.md §4.3)

Subagents cannot see CLAUDE.md or this conversation. Every dispatch pastes this template, filled:

```
## Task
{One task from the approved plan, stated precisely. One task per dispatch.}

## Context you must treat as law
- RedThread is an internal intelligence-production platform that turns Xiaohongshu (小红书)
  beauty content into English strategic insights for Western beauty and wellness brands.
- ALL artifacts in English: code, identifiers, comments, docstrings, error messages, UI copy,
  docs. Chinese appearing as DATA (XHS text, glossary terms, taxonomy slang) stays Chinese.
- schema.sql is the single source of truth; models conform to it. Never alter schema.
- Every pipeline step must be idempotent; re-running must not duplicate data or corrupt state.
- Machine outputs and analyst corrections are separate fields; never overwrite raw_* fields.
- Secrets only via env vars; never hardcode. Media is served only through authenticated routes.
- No new dependencies, tables, columns, enum values, screens, or endpoints beyond this brief.
  If the task seems to need one, STOP and return the question instead of improvising.

## Locked decisions relevant to this task
{Paste the specific decisions from plan §1 / CLAUDE.md that constrain this task.}

## Files in scope
{Explicit paths. Anything outside scope is read-only.}

## Acceptance criteria
{Bullet list; each independently checkable.}

## Output format
Terse: unified diffs or new-file contents + a ≤10-line summary + how you verified
(command + exit code + relevant tail). No full-file dumps of unchanged code.
```

---

## 5. Top risks

1. **OCR quality on stylized XHS screenshots** — mitigated by VLM-as-OCR default, golden-set eval (M5, runnable earlier once `tests/golden/` exists), provider interfaces keeping the choice reversible.
2. **Backup gate slipping** — M2 is a blocking gate *before* daily clipping; the restore drill is a fable-reviewed acceptance criterion, not an afterthought.
3. **30s triage metric erosion** — every Triage/UI decision is tested against the stopwatch in M4 review; hotkey map locked up front.
4. **Idempotency subtleties in retry cascades** — designed explicitly ([fable] 3.1) before implementation, with forced-failure verification in M3.
5. **Embedding model regret** — bilingual-concat input + cosine + text-embedding-3-small pinned now; re-embed path (iron law #2) makes a later switch survivable while the corpus is small.
6. **Cost drift** — per-post cost logged from M3; eval reports cost as a first-class metric; ceilings re-checked in M8 dogfood.
