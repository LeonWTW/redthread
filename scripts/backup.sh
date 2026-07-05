#!/usr/bin/env bash
# RedThread nightly backup — SKELETON (M0). Implemented fully in M2 (task 2.6).
# Runs on the Hetzner VPS via cron; targets Backblaze B2 (kickoff decision 17b).
# This is a BLOCKING GATE: must be live before daily clipping starts (CLAUDE.md §6).
#
# Plan (M2):
#   1. pg_dump the redthread database from the postgres container to a dated file.
#   2. Sync the media volume + dumps to B2 with restic (encrypted, deduplicated).
#   3. Prune old snapshots per retention policy (e.g. 7 daily, 4 weekly, 6 monthly).
#   4. Exit non-zero on any failure so cron mails the analyst.
#
# Restore drill: documented in docs/runbook.md; exercised monthly.

set -euo pipefail

echo "backup.sh is a skeleton until M2 (task 2.6); refusing to pretend it ran." >&2
exit 1
