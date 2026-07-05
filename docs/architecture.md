# Architecture

## Overview

RedThread is a containerized web application organized around an asynchronous enrichment pipeline. A React single-page client serves the analyst's five screens; a Flask API handles authentication, capture, CRUD, search, and report assembly; Celery workers execute the pipeline steps against external AI services through provider interfaces; PostgreSQL is the system of record; Qdrant stores one embedding vector per post for semantic search; media files live in a private volume served only through authenticated routes. Everything starts with a single Docker Compose command.

Two workflow loops drive the design: a daily triage loop (capture and annotate, 10–20 minutes) and a weekly report loop (~1 hour). Architectural choices are judged by whether they make one of these loops faster or more trustworthy.

## Major Components

- Client / User Interface — React SPA (Inbox, Triage, Library, Report Editor, Export Preview)
- Server / Application Logic — Flask API
- Async Pipeline — Celery workers on a Redis broker
- AI Provider Layer — OCRProvider, TranslationProvider, ExtractionProvider, EmbeddingProvider interfaces
- Data / Persistence — PostgreSQL (system of record), Qdrant (vector index), private media volume (MediaStore interface)

## Component Responsibilities

Client (React SPA). Renders the five analyst screens. Triage is keyboard-first (hotkeys for taxonomy annotation, save-and-next) because per-post handling time is a critical metric. The Report Editor attaches citation chips to claims and opens cited posts in a side panel for verification. The client holds no business logic that matters for correctness; enforcement lives server-side.

API server (Flask). Authenticates the single analyst account (session cookie on all routes, including media) and machine clients (token-authenticated capture endpoint, rate-limited login). Accepts captures (images, URLs, CSV), parses Xiaohongshu note IDs for duplicate detection, enqueues pipeline work, serves search by combining Qdrant results with PostgreSQL records, and enforces the report invariant: a claim cannot be saved without a citation.

Pipeline workers (Celery + Redis). Execute the enrichment chain — OCR per image, translation and entity extraction at post level, embedding — as a four-task Celery chain (`ocr_post → translate_post → extract_post → embed_post`) of independent, idempotent, individually retryable steps, writing per-step status that the Inbox displays. Idempotency and retry follow the force/skip-on-success design (docs/plans/002-pipeline-idempotency.md): every task takes `(post_id, force=False)`; with `force=False` a step whose status is already `success` returns immediately without touching data, so re-enqueuing the whole chain is always safe; a per-step retry from the Inbox enqueues that step and all downstream steps with `force=True`, resetting their statuses to `pending` in the same transaction (upstream changed, so downstream machine outputs are stale by definition). Forced re-runs overwrite only machine fields (`machine_translation`, entities from an explicit extract retry, the Qdrant point) and never analyst fields (`corrected_*`, `final_translation`). Transient provider errors self-retry twice with backoff before landing in `failed`; configuration errors surface as non-retryable guidance. Corrections to text or translation enqueue a forced re-embed, keeping the vector index consistent with the analyst-corrected record.

AI provider layer. Every external AI capability sits behind an interface selected by configuration (`.env`), so providers can be swapped without touching pipeline code. As built: OCR, translation, and entity extraction run on Anthropic Haiku (a vision-capable model used as OCR, per the stylized-screenshot rationale below) behind `OCRProvider` / `TranslationProvider` / `ExtractionProvider`; embedding runs on OpenAI `text-embedding-3-small` behind `EmbeddingProvider`, over a pinned bilingual-concat document — the Chinese source text (corrected text falling back to raw OCR aggregate, plus caption) concatenated with the English translation (final falling back to machine) — so mixed Chinese/English queries land in the same vector space (docs/plans/002-pipeline-idempotency.md). A 20-post golden set with human ground truth drives provider evaluation (`scripts/eval_providers.py` wrapping `server/app/eval/harness.py`), scoring accuracy and per-post cost together against an explicit cost ceiling.

Persistence. PostgreSQL holds posts, post images (multi-image carousels, with comment screenshots typed as comment evidence), annotations (fixed taxonomy), glossary, reports, and citations; a single schema file is the source of truth. Machine outputs and analyst corrections are stored as separate fields (raw vs. corrected OCR; machine vs. final translation) so nothing the model produced is ever silently overwritten. Qdrant stores one vector per post. Media files are private and served only through an authenticated route. Nightly backups of the database and media go to off-server storage.

## Data Flow

1. The analyst captures a post: uploads screenshots from a phone, pastes a URL, or imports a CSV; trusted external clients can POST to the capture API. A parsed note ID that already exists returns "already captured"; a near-duplicate image raises a soft warning.
2. The API stores the post and image records, saves media to the private store, and enqueues the pipeline.
3. Workers run OCR on each image, aggregate text at the post level (comment-section text marked as such), translate with glossary injection, extract entities, and embed the post into Qdrant. Each step records status; failures are retryable per step.
4. In Triage, the analyst reviews the bilingual record, corrects OCR or translation inline (corrections trigger re-embedding), and annotates against the taxonomy via hotkeys.
5. In Library, semantic search (English, Chinese, or mixed queries) returns annotated bilingual cards; the analyst adds relevant posts to a report.
6. In the Report Editor, claims are composed with citation chips resolving to captured posts; the server rejects uncited claims.
7. Export renders the report template (brand watch, trend radar with a per-trend crossover assessment block, negative calls, glossary-driven consumer-language decoder) as styled HTML from a single Jinja2 template (`server/app/export/`) and prints it to PDF with Playwright driving a Chromium bundled inside the api image; the same template produces the public web variant (confidential footer swapped, citation anchors intact). Citation numbering and evidence-appendix assembly live in one place (`app/export/queries.py`); the template only consumes prepared data.

## Initial Architecture Sketch

```
 iPhone screenshots / URL paste / CSV        token clients
                 │                                │
                 ▼                                ▼
        ┌─────────────────────┐          POST /api/capture
        │  React SPA          │                  │
        │  Inbox · Triage     │                  │
        │  Library · Report   │                  │
        │  Editor · Export    │                  │
        └─────────┬───────────┘                  │
                  │ HTTPS (session cookie)       │
        ┌─────────▼───────────────────────────────▼─┐
        │                Flask API                   │
        │ auth · capture · dedup · CRUD · search ·   │
        │ report invariants · authenticated media    │
        └───────┬──────────────────────┬────────────┘
                │ enqueue              │ read/write
        ┌───────▼───────┐      ┌───────▼───────┐
        │  Redis broker │      │  PostgreSQL   │
        └───────┬───────┘      │ (schema.sql = │
                │              │ source of     │
        ┌───────▼──────────┐   │ truth)        │
        │  Celery workers  │──►└───────────────┘
        │  OCR → translate │
        │  → extract →     │──► external AI provider APIs
        │  embed (idempo-  │    (via provider interfaces)
        │  tent steps)     │
        └───────┬──────────┘
                │ vectors (1 per post)
        ┌───────▼───────┐     ┌────────────────────────┐
        │    Qdrant     │     │ Private media volume   │
        └───────────────┘     │ (authenticated serving)│
                              └────────────────────────┘
```

## Open Questions

- Golden-set eval verdicts: the harness is built and structure-checked, but live accuracy × cost verdicts (Anthropic Haiku vision as OCR vs. self-hosted PaddleOCR — Xiaohongshu screenshots feature stylized fonts, stickers, and emoji that traditional OCR handles poorly — plus translation/extraction quality) await real provider API keys and the real 20-post golden set with human ground truth. The provider interfaces keep every default reversible.
- Model tier per pipeline task: which tasks are adequate on the cheapest model tier and which need escalation, within the $0.05-per-post ceiling. Decided by the same golden-set evaluation, not by debate.
- Deployment: the target is Leon's existing Hetzner VPS via Docker Compose (docs/decisions.md), but the stack currently runs only on the development Mac; VPS deployment — and activating the Backblaze B2 backup target with a passed restore drill there — is pending.
- Multi-tenant provisioning: a defaulted platform column on posts is the only reservation for future expansion; beyond that, nothing structural. Revisit only on demonstrated demand.
