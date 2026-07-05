# Verification 002 — M2 Capture Hardening + Backup

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M2
Built via dynamic workflow wf_6bf9d427-6b7 (4 parallel implementers + verifier),
fable-reviewed in the main loop (xhs.py, phash.py, capture route diff).

## What was tested (verifier: 6/6 PASS)

1. **Full test suite** — `docker compose run --rm api pytest -q`: **96 passed**
   (61 existing + 35 new: 24-case XHS URL parse matrix; URL dedup roundtrip;
   pHash distance-0 duplicate warning + different-image no-warning; unreadable
   image → 400; defer/append/process sequential-upload flow; CSV happy path /
   duplicate / missing url / bad captured_at / notes→annotation upsert /
   token-auth rejected on CSV). Run twice — same result (cleanup verified).

2. **Client build** — exit 0 (174 kB / 57 kB gzip).

3. **Live URL dedup** — token-authed capture with an explore URL → 202 +
   post_id; identical repeat → **200 already_captured, same post_id**; rows
   cleaned up. (Caveat found: containers must be restarted after code edits —
   volume-mounted code loads at process start; noted in runbook.)

4. **Live CSV import** — session-authed 2-row CSV → created:1, duplicates
   row 2; cleaned up.

5. **Backup + restore drill (real run, local restic repo)** — backup.sh exit 0
   (pg_dump custom format, restic snapshot incl. media volume, retention
   forget/prune); restore_drill.sh exit 0 **PASS** (scratch db redthread_drill
   restored + row-counts verified + dropped; temp dirs removed). Loud-failure
   path verified (unset RESTIC_PASSWORD → clear error, exit 1). Retention
   verified (4th dump created → 3 remain). Platform issue found and fixed by
   the implementer: restic's O_NOATIME open fails with EIO under Docker
   Desktop's macOS file sharing — dumps are now staged with cp inside the
   container before `restic backup`; unchanged behavior on the Linux VPS.

6. **Docs** — watchlist.md (7 brands + 5 KOC slots), runbook.md (real cron
   line with flock, drill-log first row).

## Gate status (BLOCKING GATE for daily clipping)

The backup **mechanism** is implemented and drill-verified locally. The gate is
NOT yet armed in production because it needs from Leon:
(a) Backblaze B2 account + `B2_KEY_ID`/`B2_APP_KEY`/`B2_BUCKET` (+
`RESTIC_REPOSITORY=b2:<bucket>:redthread`, `RESTIC_PASSWORD`) in the VPS .env;
(b) the compose stack deployed on the Hetzner VPS (or a Tailscale-reachable
Mac) so the iPhone can reach the capture page;
(c) `ANTHROPIC_API_KEY` for real OCR/translation.
Daily clipping must not start before (a) is live and one B2-backed
backup + drill has passed on the VPS.

## What changed

server/app/xhs.py, phash.py (new); routes/capture.py extended (url dedup,
defer_pipeline, CSV import); routes/posts.py + append-image & process
endpoints; client Capture page rebuilt (sequential per-file upload + retry,
URL paste, CSV import, soft near-dup warnings, 390px-friendly);
scripts/backup.sh (real), scripts/restore_drill.sh (new); runbook filled;
watchlist seeded; .env.example restic vars.
