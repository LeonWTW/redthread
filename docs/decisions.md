# Decisions Log

Running record of business/engineering decisions made outside the founding
documents. The founding constitution is CLAUDE.md; the approved implementation
plan is docs/plans/001-mvp-plan.md (its §1 lists the 18 kickoff decisions in full).

## 2026-07-05 — Sprint 2 kickoff (Leon)

- **Plan 001 approved.** Autonomous execution via dynamic workflows authorized.
- **Sprint 2 calendar deadline: not tracked.** Leon explicitly declined to set
  one ("不用care about deadline" — build to completion in dependency order).
- **CLAUDE.md amendment:** `posts.platform TEXT NOT NULL DEFAULT 'xhs'` added to
  §6 schema decisions — the only structural reservation for future platform
  expansion (demand-pull strategy formally recorded).
- **Embedding input pinned:** bilingual concatenation — zh corrected_text
  (fallback full_ocr_text) + separator + en final_translation (fallback
  machine_translation). Rationale in plan §1.
- **HEIC:** rejected in v1 with a friendly "upload a screenshot instead"
  message; no pillow-heif. Camera photos are a v2 concern.
- **CSV import columns:** `url, caption, captured_at, notes`; only `url` required.
- **Providers:** Anthropic Haiku vision (OCR), Haiku (translate/extract),
  OpenAI text-embedding-3-small (embedding). Keys Leon holds:
  ANTHROPIC_API_KEY, OPENAI_API_KEY.
- **Backup target:** Backblaze B2 (Leon will create the account).
- **Deployment:** Leon's existing Hetzner VPS via Docker Compose; dev on Mac.
- **Triage hotkeys completed:** trend_type A/S/D/F/G/H; recommended_action
  7/8/9/0 (category 1–4, consumer_signal Q–T, origin Z/X/C/V per CLAUDE.md §5).
- **Entity schema:** brand | product | ingredient | other;
  {text_zh, text_en, type, confidence} JSONB on posts; confidence is a model
  self-reported heuristic (not calibrated), displayed for entities only.
