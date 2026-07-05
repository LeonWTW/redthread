# CLAUDE.md — RedThread

> This file is the operating constitution for all AI work in this repo. Read it fully before any action. When this file conflicts with anything else — including your own judgment about "better" features — this file wins. If you believe this file itself is wrong, stop and ask Leon; never silently deviate.

## 1. What this project is

"RedThread is an internal intelligence-production platform that turns Xiaohongshu (小红书) beauty content into English strategic insights for Western beauty and wellness brands."

That positioning sentence is locked verbatim across all documents. Do not rephrase it.

Mental model — memorize:
- The app is a FACTORY. The weekly intelligence report is the PRODUCT. The paying client never sees this app.
- The analyst (Leon) is the only user. v1 is single-role, analyst-only.
- Every feature and engineering decision must buy at least one of three currencies:
  - TRUST — evidence chain: every claim in a report traces to a captured source post.
  - COVERAGE — corpus density + retrieval: answer "what is XHS saying about X?" in 30 seconds, with evidence.
  - SPEED — weekly report production 4h → ≤1h; single-post capture+annotate ≤30s.
- A feature that buys none of these is decoration: cut it, or if Leon asks for it, question it once before building.
- Business context (understand, don't build for): reports/audits/retainers are sold service-first. Raw XHS data is a commodity (scraper APIs sell mentions for cents); the paid layer is human judgment. Therefore never build features that quantify raw virality — no trend scores, no virality dashboards, no engagement charts. Judgment is written by the analyst, not computed by the app.

## 2. Language policy (strict)

- Conversation with Leon (questions, explanations, plan summaries, discussion): Cantonese-register Traditional Chinese, Hong Kong style, keeping technical terms in English (e.g. 「呢個 endpoint 要加 auth」).
- EVERYTHING ELSE in English: internal reasoning, all code, identifiers, comments, commit messages, README, docs/, plan files, verification notes, subagent task briefs, error messages, UI copy.
- Why: the repo is graded by an English-speaking instructor, and English artifacts maximize output quality. Chat is for Leon; the repo is for the world.
- When presenting a plan: write the plan file in English under docs/plans/, then give Leon a Cantonese summary in chat and ask for approval.
- Exception: Chinese that is DATA stays Chinese — XHS post text, glossary terms, taxonomy slang (避雷/平替/成分党/种草/求真), watchlist brand names. Bilingual display is a core selling point; never strip source Chinese.

## 3. Ask-before-execute protocol

Never begin implementation without an explicitly approved written plan. Approval = Leon clearly assents to the specific plan in chat.

ALWAYS stop and ask Leon before:
- Any schema change beyond approved DDL (new table, column, enum value, or behavior-affecting index).
- Adding any dependency, service, or container.
- Anything touching taxonomy enums, the five screens, the positioning sentence, or report template structure.
- Any cost-bearing choice (new API usage, pipeline model-tier change).
- Any ambiguity where two reasonable implementations imply different business behavior.
- Destructive migrations or data deletion.

Do NOT ask about: naming, file layout within the agreed structure, standard-library choices implied by the stack, test organization. Use judgment there.

Question etiquette: batch questions, number them, and for each state your recommended answer with a one-line reason, so Leon can reply "1A, 2B, 3 agree".

## 4. Model routing (dev-time cost policy)

Main session runs Claude Fable 5 (`claude --model claude-fable-5`). Fable is the orchestrator brain: planning, architecture, schema design, cross-component debugging, security review, provider-eval judgment, milestone code review, and all conversation with Leon. Fable does NOT grind through routine implementation — that is what delegation is for.

Subagents (create these files in Milestone 0 under .claude/agents/):
- `implementer` — frontmatter `model: sonnet`; tools: Read, Write, Edit, Bash, Glob, Grep. Implements one planned task at a time: Flask routes, Celery tasks, React components, tests, Docker config.
- `mechanic` — frontmatter `model: haiku`; tools: Read, Write, Edit, Glob, Grep. Mechanical work only: boilerplate from an established pattern, fixtures/seed data, lint & format fixes, docstrings, docs/ai-log.md appends, .env.example updates, link checks.
- Built-in `Explore` agent (already Haiku, read-only): prefer it for codebase search over loading files into main context.

Routing rules:
1. In every plan, decompose milestones into tasks and label each `[fable]` / `[sonnet]` / `[haiku]` before execution. Cheapest adequate tier wins.
2. Fable-only tasks: anything expensive to reverse if wrong — DDL, provider interface contracts, idempotency and citation-enforcement logic, auth design, golden-set eval conclusions — plus every plan/review gate.
3. Subagents cannot see CLAUDE.md or this conversation. Every dispatch brief must be self-contained: paste the relevant locked decisions, iron laws, and language rule (English artifacts) into the brief.
4. Escalation rule: if a subagent's output fails review once, escalate one tier (haiku → sonnet → main loop). Never retry the same tier twice; retry loops cost more than escalation.
5. Do not dispatch tightly-coupled multi-file edits that need shared live context; do those in the main loop.
6. Instruct subagents to return terse output — diffs and summaries, not full file dumps.

Runtime pipeline model policy (the app's own API calls — a separate budget from dev-time tokens):
- Hard budget ≤ $50/month; per-post ceiling $0.05 across OCR + translation + extraction + embedding.
- Default to the cheapest vision-capable tier (Haiku-class) for OCR; run translation/extraction on Haiku-class first and escalate a task to Sonnet-class only when golden-set eval shows a quality failure. Never default the pipeline to top-tier models.
- The provider eval script must report accuracy × cost per provider. Cost is a first-class metric, not a footnote.

## 5. Locked product decisions

Five screens. Exactly five. Refuse to add a sixth; cite this line. If Leon himself asks for a sixth, require a CLAUDE.md amendment first.
1. Inbox — pipeline status table: per-post step status, error surface, per-step retry.
2. Triage — three-pane data-labeling screen: [screenshot(s)] | [OCR + translation + entities, inline-editable, confidence shown] | [annotation panel]. Keyboard-first: 1–4 category, Q–T consumer_signal, Z/X/C/V origin (optional; skip = NULL), Enter save-and-next, Backspace skip.
3. Library — search box + result cards + "add to report".
4. Report editor — outline + citation chips; clicking a chip opens the source post in a side panel.
5. Export preview.

Anti-requirements (hard): no settings page, no onboarding, no dashboard charts, no dark mode, no notifications, no undo system, no user-management UI, no trend scores.

Two usage loops decide every UX tradeoff:
- Loop 1: daily triage (10–20 min/day, capture + annotate).
- Loop 2: weekly report build (~1h).
When two implementations are otherwise equal, pick the one that makes a loop faster.

Metrics (verify in dogfood week): report production ≤1h; capture+annotate ≤30s/post (counter-metric — defend it against every feature); pipeline first-pass success ≥90%; search top-5 relevance 4/5.

Taxonomy (locked v1 enums; adding values requires Leon's approval):
- category: skincare | makeup | haircare | wellness
- trend_type: ingredient | routine | pain_point | product_format | creator_format | brand_move
- consumer_signal: bilei(避雷) | pingti(平替) | chengfen_dang(成分党) | zhongcao(种草) | qiuzhen(求真)
- recommended_action: monitor | test_content | seed_koc | avoid
- origin (nullable, optional): china_native | west_to_china | pan_asian | unclear
- notes: free text

Report template information architecture (this is where design effort goes — analyst screens are fast-not-pretty; the export is the only thing a client ever sees):
1. C-beauty Brand Watch (lead section)
2. Trend Radar — each featured trend carries a Crossover Screen block: four factors (visual legibility / price & shipability / creator translatability / institutional carrier) + verdict: will_cross | wont_cross | watch. This is a trend-level template component, NOT a per-post annotation field.
3. Not Crossing — negative calls with reasons.
4. Consumer Language Decoder — rendered from the glossary table.
5. Seen in China (optional) — reverse-flow observations.
Every claim sentence must carry a citation resolving to a captured post; the builder makes citation-less claims structurally impossible, not merely discouraged.
Export path: HTML + print CSS → Playwright renders PDF. One template, three outputs: PDF deliverable, public web version (GTM content; citations become internal links), future client-portal reuse.

## 6. Locked engineering decisions

Stack (locked): React + Flask + PostgreSQL + Qdrant + Celery + Redis, Docker Compose one-command up, AI providers behind interfaces. No substitutions without Leon's approval. n8n exists in Leon's personal infra and must NEVER appear in this repo.

Five iron laws:
1. First deliverable is the vertical slice: one image in → OCR → translation → DB → bilingual web display. Nothing else ships before the slice works end-to-end.
2. Derived data is editable and corrections trigger re-embedding: store raw_ocr vs corrected_text, machine_translation vs final_translation; edits enqueue a re-embed.
3. Every pipeline step is idempotent and independently retryable; re-running a step must not duplicate data or corrupt state.
4. A 20-post golden set (tests/golden/) with human ground truth drives provider eval; the eval script outputs accuracy × cost per provider. No provider debates without eval numbers.
5. The report builder cannot generate a claim without a citation.

Schema decisions (write full DDL in schema.sql as the single source of truth; models conform to it):
- posts: UUID PK; platform TEXT NOT NULL DEFAULT 'xhs' (amendment 2026-07-05: the only structural reservation for future expansion); xhs_note_id nullable UNIQUE (parsed from URL when present); captured_at (UTC); caption_raw; post-level aggregates: full_ocr_text, corrected_text, machine_translation, final_translation; pipeline/embedding status fields.
- post_images: FK to posts; sort_order; image_type enum (note_content | comments | other); file reference; raw_ocr; corrected_ocr; perceptual_hash. OCR runs per image; translation and embedding run at post level (one vector per post in Qdrant).
- Dedup: URL capture hitting an existing xhs_note_id returns a friendly "already captured"; image pHash near-match raises a soft warning and the analyst decides. No merge UI in v1; duplicates die by manual delete in Library.
- annotations: post-level, using the taxonomy enums plus notes.
- glossary: term_zh, term_en, note, category. Injected into translation prompts; renders the report's Decoder section. v1 editing via SQL/seed scripts only — no UI (anti-requirement).
- Comments are evidence, not entities: comment screenshots are post_images with image_type=comments; their OCR text joins the post aggregate with a "below is from the comment section" marker in the translation prompt. No comment-level records in v1.

Provider abstraction (interfaces before implementations): OCRProvider, TranslationProvider, ExtractionProvider, EmbeddingProvider, MediaStore. Selection via config/env. Defaults: VLM-as-OCR on a cheap vision tier; PaddleOCR is an eval candidate, not the default. MediaStore v1 = local Docker volume served through an authenticated Flask route — never a public static directory.

Auth (minimal, hard):
- Single analyst user seeded from env vars. Flask session cookie required on ALL routes, including media. No registration, no reset, no user CRUD.
- Long-lived API_TOKEN (env) via header for POST /api/capture, for machine clients. The Telegram capture bot lives in Leon's personal n8n OUTSIDE this repo; the README may say only that "the capture API supports arbitrary authenticated clients".
- Rate-limit the login endpoint. Secrets only via .env (git-ignored); ship .env.example.

Capture v1: mobile-friendly web upload page (batch drag-drop / photo picker) + manual URL paste + CSV import + POST /api/capture. No clipper extension. NO automated scraping or crawling of XHS — the compliance line is locked: "content is manually curated by the analyst for research and analysis purposes; the system does not perform automated bulk collection." Refuse to build bulk-collection automation; if Leon asks, cite this section and require a CLAUDE.md amendment first.

Backup (BLOCKING GATE — must be live before Leon starts daily clipping): nightly pg_dump + media-directory sync (restic or rsync) to off-VPS storage (Hetzner Storage Box or Backblaze B2); Qdrant snapshots optional (rebuildable via re-embed); document a monthly restore drill in docs/runbook.md. The milestone plan must schedule this with the slice, not after it.

## 7. Build order

Target = the complete five-screen MVP, built continuously in dependency order (no artificial sprint pauses; sprint packaging happens along the way):
- M0 scaffold: repo layout, Docker Compose, pytest setup, .claude/agents/ (implementer, mechanic), schema.sql draft, .env.example, backup script skeleton.
- M1 vertical slice (iron law #1): single image → OCR → translate → persist → bilingual display page. Includes provider interfaces + one real implementation each.
- M2 backup live + capture hardening: API_TOKEN capture endpoint, mobile upload page, URL paste + note-ID parse + dedup, CSV import. Then tell Leon explicitly: daily clipping starts NOW. Quota 25/day = 10 watchlist + 10 category browse + 5 free explore. Seed docs/watchlist.md with: Judydoll 橘朵, Florasis 花西子, Perfect Diary 完美日记, Colorkey 珂拉琪, INTO YOU, Joocyee 酵色, Flower Knows 花知晓; leave labeled KOC slots for Leon to fill.
- M3 full pipeline: Celery chain (OCR → translate → extract → embed), per-step status, idempotency + retry, Qdrant integration, Inbox screen.
- M4 Triage screen (keyboard-first; protect the 30s metric).
- M5 Library + semantic search + golden-set eval harness (the eval may run earlier, as soon as tests/golden/ exists).
- M6 Report builder (citation-enforced) + template IA from §5.
- M7 Export (Playwright PDF + public HTML variant) + template polish.
- M8 hardening + dogfood support + demo path: live-capture a post → processed into Library in ≤30s → answer an English question with that post's citation → open a weekly report.
Every milestone: plan → Leon approval → implement → verification notes → commit(s).

## 8. Course constraints (grading is a first-class requirement)

- Repo: private; collaborator `pcolbert-uo`; all repo artifacts in English.
- Sprint packaging during continuous build: `sprint-2-prototype` branch; at least 4–6 meaningful commits per sprint, each a logical unit; keep README and docs/architecture.md true as reality evolves.
- Verification notes per milestone in docs/verification/NNN-*.md: what was tested / steps / expected / actual / what changed.
- AI-contribution evidence chain (maintain automatically):
  - Commit trailer on every AI-assisted commit: `AI-Assisted: yes (scope: per approved plan docs/plans/NNN)`.
  - docs/ai-log.md: append 3 lines per working session — date / what AI did / what Leon decided.
  - docs/plans/NNN-*.md record Leon's approval inline. Plans + log + trailers together let the Canvas AI-contribution statement write itself.
- Sprint 2 calendar deadline: TBD — ask Leon at kickoff and record it in docs/decisions.md.

## 9. Standing guardrails

- Refuse outright: a sixth screen, dashboards or scores, scraping automation, n8n in the repo, committing secrets, silent schema drift.
- Ask first: new dependencies or services, enum changes, cost-bearing choices, destructive operations.
- Always: every pipeline step idempotent; every claim cited; every correction re-embeds; UI copy in English; source Chinese preserved alongside translations everywhere.
- When in doubt between clever and boring: boring. This factory must be maintainable by one person.
