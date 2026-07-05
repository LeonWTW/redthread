# RedThread Runbook

Stub created in M0; filled in as operations land.

## Backup (M2 — blocking gate before daily clipping)

- Nightly cron on the Hetzner VPS runs `scripts/backup.sh`:
  `pg_dump` + media volume sync to Backblaze B2 (restic).
- Secrets: `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET` via `.env` on the VPS.

## Restore drill (monthly)

_To be documented in M2 with the exact commands, and exercised once as an M2
acceptance criterion. Each drill appends a dated entry here._

| Date | Result | Notes |
|------|--------|-------|

## Service recovery

_To be documented as services land: how to restart the stack, re-run a stuck
pipeline step, rebuild the Qdrant index via re-embed._
