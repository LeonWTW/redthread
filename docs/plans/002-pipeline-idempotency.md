# Design Note 002 — Pipeline Idempotency & Retry Semantics (M3, plan 001 task 3.1)

Status: design for implementation (authored by the orchestrator per approved
plan 001; implements kickoff decisions 6 and 12 and iron law #3).

## Chain

`ocr_post → translate_post → extract_post → embed_post` as a Celery chain of
immutable signatures, one task per step per post. A step that raises stops the
chain (Celery semantics), always after persisting its status + error taxonomy.

## The force flag (skip-on-success vs. explicit re-run)

Every task takes `(post_id, force=False)`.

- `force=False` (normal enqueue, `/api/posts/<id>/process`, capture): a step
  whose status is already `success` **returns immediately without touching
  data**. This makes re-enqueuing the whole chain safe at any time — the
  cheapest possible idempotency, and it protects analyst-edited `entities`
  from being clobbered by an incidental chain re-run.
- `force=True` (explicit per-step retry from the Inbox): the step re-runs its
  work and overwrites its own **machine** outputs. Retrying step N enqueues a
  chain of steps N..end **all with force=True** (kickoff decision 6: upstream
  changed, downstream outputs are stale by definition).

Within-step idempotency is unchanged from M1: OCR only processes images whose
`raw_ocr IS NULL` (under force, raw_ocr of previously-OCR'd images is still
preserved — force at the OCR level re-runs only missing images and always
recomputes the deterministic aggregate); translate/extract/embed overwrite
only machine fields (`machine_translation`, `entities`, the Qdrant point),
never analyst fields (`corrected_*`, `final_translation`).

Note on `entities`: schema v1 stores one JSONB column (kickoff decision 15) —
machine output and analyst edits share it. Protection is procedural: nothing
overwrites `entities` except (a) first successful extract and (b) an explicit
analyst-initiated retry of the extract step. This is the recorded tradeoff.

## Step inputs

- zh source (shared helper, same for translate/extract/embed):
  `caption_raw + "\n\n" + (corrected_text || full_ocr_text)` (either side may
  be absent; comment-section marker lives inside the OCR aggregate).
- extract: zh source + `final_translation || machine_translation`.
- embed document (pinned bilingual concat, plan 001 §1): zh source +
  `"\n---\n"` + `(final_translation || machine_translation)`. If both sides
  are empty the step sets `skipped`. `embedded_at` is set on success.

## Qdrant write idempotency

Collection `posts` (cosine, dim 1536) is create-if-missing on first use.
Writes are upserts keyed by the post UUID — re-embedding replaces the point;
no duplicates are possible. Payload: `{"post_id"}` only.

## Corrections → re-embed (iron law #2)

`PATCH /api/posts/<id>` accepting `corrected_text` / `final_translation` /
`entities`. Any change to `corrected_text` or `final_translation` enqueues
`embed_post(post_id, force=True)` (embed only — extraction is not re-run
implicitly; the analyst can retry extract explicitly if the text change
invalidates entities). Editing `entities` does not re-embed (entities are not
part of the embed document). Per-image `corrected_ocr` edits
(`PATCH /api/posts/<id>/images/<image_id>`) store the correction; the
post-level `corrected_text` remains the analyst's authoritative aggregate.

## Addendum (2026-07-05, post-verification adjudication)

The retry endpoint resets the retried step and all downstream steps to
`pending` (clearing their error taxonomy) in the same transaction that
enqueues the forced chain. Rationale: without the reset, a chain that stops at
a still-failing step leaves stale `failed`/`success` badges on downstream
steps the analyst just asked to re-run — the Inbox would lie. Skip-on-success
semantics are unaffected because the forced chain ignores statuses anyway.

## Error taxonomy & retries (unchanged, now on all four steps)

`TransientProviderError` → Celery self-retry ×2 (10s, 30s) with status held at
`running`, then `failed`. Other `ProviderError`s → `failed` immediately.
Unexpected exceptions → `failed` with `storage_error`. Status + error_type +
error_message are written before any raise. `config_error` is rendered as
non-retryable guidance in the Inbox.
