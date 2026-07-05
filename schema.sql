-- =============================================================================
-- RedThread — schema.sql
-- Single source of truth for the relational schema (CLAUDE.md §6).
-- Models conform to this file, never the reverse.
-- Locked decisions: docs/plans/001-mvp-plan.md §1 and docs/decisions.md.
-- Target: PostgreSQL 16.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

-- Pipeline step status (decision 1). 'skipped' covers steps with nothing to do
-- (e.g. OCR on a caption-only post).
CREATE TYPE step_status AS ENUM ('pending', 'running', 'success', 'failed', 'skipped');

-- Per-step error taxonomy (decision 12).
CREATE TYPE error_type AS ENUM (
    'transient',       -- timeout / rate limit / 5xx; auto-retried before surfacing
    'provider_error',  -- provider 4xx / refusal
    'parse_error',     -- malformed model output
    'config_error',    -- missing/invalid key or config; retry is futile
    'storage_error'    -- media or DB write failure
);

CREATE TYPE image_type AS ENUM ('note_content', 'comments', 'other');

-- Annotation taxonomy (CLAUDE.md §5, locked v1; adding values requires Leon's approval).
CREATE TYPE category AS ENUM ('skincare', 'makeup', 'haircare', 'wellness');
CREATE TYPE trend_type AS ENUM (
    'ingredient', 'routine', 'pain_point', 'product_format', 'creator_format', 'brand_move'
);
CREATE TYPE consumer_signal AS ENUM ('bilei', 'pingti', 'chengfen_dang', 'zhongcao', 'qiuzhen');
CREATE TYPE recommended_action AS ENUM ('monitor', 'test_content', 'seed_koc', 'avoid');
CREATE TYPE origin AS ENUM ('china_native', 'west_to_china', 'pan_asian', 'unclear');

-- Report structure (CLAUDE.md §5 template IA).
CREATE TYPE report_section AS ENUM (
    'brand_watch',    -- 1. C-beauty Brand Watch (lead section)
    'trend_radar',    -- 2. Trend Radar (trend blocks carry a Crossover Screen)
    'not_crossing',   -- 3. Not Crossing (negative calls)
    'decoder',        -- 4. Consumer Language Decoder (rendered from glossary)
    'seen_in_china'   -- 5. Seen in China (optional reverse-flow observations)
);
CREATE TYPE crossover_verdict AS ENUM ('will_cross', 'wont_cross', 'watch');
CREATE TYPE report_status AS ENUM ('draft', 'final');

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- ---------------------------------------------------------------------------
-- posts
-- ---------------------------------------------------------------------------
-- Aggregates live at post level: OCR text is aggregated from images; translation
-- and embedding run once per post (one vector per post in Qdrant, point ID = posts.id).
-- Machine outputs and analyst corrections are separate columns; raw_* / machine_*
-- are never overwritten (iron law #2).

CREATE TABLE posts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Amendment 2026-07-05: the only structural reservation for future expansion.
    platform            TEXT NOT NULL DEFAULT 'xhs',
    xhs_note_id         TEXT,             -- parsed from URL when present; unique when present
    source_url          TEXT,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),  -- business fact; CSV import may backfill
    caption_raw         TEXT,

    -- Post-level aggregates (zh side, then en side).
    full_ocr_text       TEXT,
    corrected_text      TEXT,
    machine_translation TEXT,
    final_translation   TEXT,

    -- Entity extraction output (decision 15): JSONB array of
    -- {text_zh, text_en, type: brand|product|ingredient|other, confidence}.
    -- Confidence is a model self-reported heuristic, not a calibrated probability.
    entities            JSONB,

    -- Per-step pipeline status (decision 1).
    ocr_status          step_status NOT NULL DEFAULT 'pending',
    translate_status    step_status NOT NULL DEFAULT 'pending',
    extract_status      step_status NOT NULL DEFAULT 'pending',
    embed_status        step_status NOT NULL DEFAULT 'pending',

    ocr_error_type          error_type,
    ocr_error_message       TEXT,
    translate_error_type    error_type,
    translate_error_message TEXT,
    extract_error_type      error_type,
    extract_error_message   TEXT,
    embed_error_type        error_type,
    embed_error_message     TEXT,

    embedded_at         TIMESTAMPTZ,      -- last successful embed; staleness aid

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dedup: URL capture hitting an existing note ID returns "already captured" (CLAUDE.md §6).
CREATE UNIQUE INDEX posts_xhs_note_id_key ON posts (xhs_note_id) WHERE xhs_note_id IS NOT NULL;
CREATE INDEX posts_captured_at_idx ON posts (captured_at DESC);

CREATE TRIGGER posts_updated_at BEFORE UPDATE ON posts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- post_images
-- ---------------------------------------------------------------------------
-- OCR runs per image. Comment screenshots are evidence, not entities:
-- image_type = 'comments' joins the post aggregate with a comment-section marker
-- in the translation prompt. No comment-level records in v1.

CREATE TABLE post_images (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id         UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    image_type      image_type NOT NULL DEFAULT 'note_content',
    file_path       TEXT NOT NULL,        -- MediaStore reference, relative to MEDIA_ROOT
    raw_ocr         TEXT,
    corrected_ocr   TEXT,
    -- 64-bit perceptual hash; near-match via app-level Hamming scan (decision 3).
    perceptual_hash BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX post_images_post_id_idx ON post_images (post_id, sort_order);

CREATE TRIGGER post_images_updated_at BEFORE UPDATE ON post_images
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- annotations
-- ---------------------------------------------------------------------------
-- Post-level, one row per post (decision 3). Fields are nullable: the analyst
-- may save a partial annotation; origin skip = NULL is explicitly allowed.

CREATE TABLE annotations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id             UUID NOT NULL UNIQUE REFERENCES posts(id) ON DELETE CASCADE,
    category            category,
    trend_type          trend_type,
    consumer_signal     consumer_signal,
    recommended_action  recommended_action,
    origin              origin,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER annotations_updated_at BEFORE UPDATE ON annotations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- glossary
-- ---------------------------------------------------------------------------
-- Injected into translation prompts; renders the report's Decoder section.
-- v1 editing via SQL/seed scripts only — no UI (anti-requirement).

CREATE TABLE glossary (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    term_zh     TEXT NOT NULL UNIQUE,
    term_en     TEXT NOT NULL,
    note        TEXT,
    category    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER glossary_updated_at BEFORE UPDATE ON glossary
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- reports / report_blocks / report_citations
-- ---------------------------------------------------------------------------
-- Iron law #5: the report builder cannot generate a claim without a citation.
-- Enforced structurally at the DB layer via deferred constraint triggers below:
-- a 'claim' block must have >= 1 citation by transaction commit, and the last
-- citation of a claim cannot be deleted while the claim exists.

CREATE TABLE reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    week_of     DATE,
    status      report_status NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER reports_updated_at BEFORE UPDATE ON reports
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE report_blocks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id       UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    section         report_section NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    -- 'claim': a sentence that must carry >= 1 citation.
    -- 'trend': a Trend Radar item carrying the Crossover Screen (trend-level
    --          template component, NOT a per-post annotation field).
    block_type      TEXT NOT NULL CHECK (block_type IN ('claim', 'trend')),
    -- Claims under a trend reference their trend block.
    parent_block_id UUID REFERENCES report_blocks(id) ON DELETE CASCADE,
    text_content    TEXT,             -- claim sentence, or trend summary
    trend_title     TEXT,             -- trend blocks only
    -- Crossover Screen: {visual_legibility, price_shipability,
    --                    creator_translatability, institutional_carrier} (free text per factor).
    crossover           JSONB,
    crossover_verdict   crossover_verdict,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT claim_has_text CHECK (block_type <> 'claim' OR text_content IS NOT NULL),
    CONSTRAINT trend_has_title CHECK (block_type <> 'trend' OR trend_title IS NOT NULL)
);

CREATE INDEX report_blocks_report_idx ON report_blocks (report_id, section, sort_order);

CREATE TRIGGER report_blocks_updated_at BEFORE UPDATE ON report_blocks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ON DELETE RESTRICT (decision 4): a cited post cannot be deleted; the evidence
-- chain (TRUST) outranks tidy deletion. Library surfaces "cited in report X".
CREATE TABLE report_citations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_id    UUID NOT NULL REFERENCES report_blocks(id) ON DELETE CASCADE,
    post_id     UUID NOT NULL REFERENCES posts(id) ON DELETE RESTRICT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (block_id, post_id)
);

CREATE INDEX report_citations_post_idx ON report_citations (post_id);

-- --- Citation enforcement (deferred to transaction commit) ------------------
-- The API must insert a claim block and its citations in one transaction.

CREATE OR REPLACE FUNCTION trg_claim_requires_citation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.block_type = 'claim' AND NOT EXISTS (
        SELECT 1 FROM report_citations c WHERE c.block_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'claim block % has no citation; uncited claims are structurally forbidden (iron law #5)', NEW.id;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER claim_requires_citation
    AFTER INSERT OR UPDATE ON report_blocks
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_claim_requires_citation();

CREATE OR REPLACE FUNCTION trg_citation_delete_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- If the claim block still exists at commit time, it must retain a citation.
    IF EXISTS (
        SELECT 1 FROM report_blocks b
        WHERE b.id = OLD.block_id AND b.block_type = 'claim'
    ) AND NOT EXISTS (
        SELECT 1 FROM report_citations c WHERE c.block_id = OLD.block_id
    ) THEN
        RAISE EXCEPTION 'cannot remove the last citation from claim block % (iron law #5)', OLD.block_id;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER citation_delete_guard
    AFTER DELETE ON report_citations
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION trg_citation_delete_guard();
