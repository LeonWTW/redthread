#!/usr/bin/env bash
# RedThread restore drill (M2 task 2.6). Run monthly — see docs/runbook.md.
#
# Verifies that backups made by scripts/backup.sh are actually restorable:
#   1. restic restore latest -> temp dir (via the restic/restic docker image).
#   2. pg_restore the newest restored dump into a scratch database
#      (redthread_drill), verify row counts on posts + glossary, then drop it.
#   3. Verify at least one media file was restored whenever the live media
#      volume contains any files.
# Prints a PASS/FAIL summary and exits 0 only on PASS. Never touches the real
# database or media volume (media is mounted read-only, count only).

set -euo pipefail

log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${BACKUP_ENV_FILE:-$COMPOSE_DIR/.env}"
DRILL_DB="redthread_drill"
RESTORE_DIR="$COMPOSE_DIR/backups/.drill-restore-$$"

# --- Load .env; variables already exported by the caller take precedence -----
_pre_restic_repository="${RESTIC_REPOSITORY:-}"
_pre_restic_password="${RESTIC_PASSWORD:-}"
_pre_b2_account_id="${B2_ACCOUNT_ID:-}"
_pre_b2_account_key="${B2_ACCOUNT_KEY:-}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  log "WARNING: env file $ENV_FILE not found; relying on exported environment only"
fi

if [[ -n "$_pre_restic_repository" ]]; then RESTIC_REPOSITORY="$_pre_restic_repository"; fi
if [[ -n "$_pre_restic_password" ]]; then RESTIC_PASSWORD="$_pre_restic_password"; fi
if [[ -n "$_pre_b2_account_id" ]]; then B2_ACCOUNT_ID="$_pre_b2_account_id"; fi
if [[ -n "$_pre_b2_account_key" ]]; then B2_ACCOUNT_KEY="$_pre_b2_account_key"; fi

export B2_ACCOUNT_ID="${B2_ACCOUNT_ID:-${B2_KEY_ID:-}}"
export B2_ACCOUNT_KEY="${B2_ACCOUNT_KEY:-${B2_APP_KEY:-}}"

if [[ -z "${RESTIC_REPOSITORY:-}" ]]; then
  die "RESTIC_REPOSITORY is unset. Set it in $ENV_FILE (must point at the repository to drill against)."
fi
if [[ -z "${RESTIC_PASSWORD:-}" ]]; then
  die "RESTIC_PASSWORD is unset. Set it in $ENV_FILE."
fi
export RESTIC_REPOSITORY RESTIC_PASSWORD

PGUSER="${POSTGRES_USER:-redthread}"
PROJECT_NAME="$(printf '%s' "${COMPOSE_PROJECT_NAME:-$(basename "$COMPOSE_DIR")}" | tr '[:upper:]' '[:lower:]')"
MEDIA_VOLUME="${PROJECT_NAME}_mediadata"

compose() { (cd "$COMPOSE_DIR" && docker compose "$@"); }

RESTIC_DOCKER_ARGS=(
  --rm
  -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY
  -v "$RESTORE_DIR:/restore"
)
if [[ "$RESTIC_REPOSITORY" == /* ]]; then
  RESTIC_DOCKER_ARGS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi
restic_run() { docker run "${RESTIC_DOCKER_ARGS[@]}" restic/restic "$@"; }

STATUS="FAIL"
on_exit() {
  rm -rf "$RESTORE_DIR" || true
  compose exec -T postgres dropdb --if-exists -U "$PGUSER" "$DRILL_DB" > /dev/null 2>&1 || true
  log "=== RESTORE DRILL: $STATUS ==="
}
trap on_exit EXIT

mkdir -p "$RESTORE_DIR"

# --- Step 1: restore the latest snapshot ----------------------------------------
log "step 1/3: restic restore latest -> $RESTORE_DIR"
restic_run restore latest --target /restore
# Snapshot paths are absolute (/data/backups, /data/media), preserved under target.
RESTORED_BACKUPS="$RESTORE_DIR/data/backups"
RESTORED_MEDIA="$RESTORE_DIR/data/media"

# Filenames embed the UTC timestamp, so lexicographic order is chronological.
# (Do not use ls -t: restored mtimes are not reliable on all mounts.)
newest_dump="$(ls -1 "$RESTORED_BACKUPS"/redthread-*.dump 2>/dev/null | sort | tail -n 1 || true)"
if [[ -z "$newest_dump" ]]; then
  die "no redthread-*.dump found in restored snapshot ($RESTORED_BACKUPS)"
fi
log "newest restored dump: $newest_dump"

# --- Step 2: pg_restore into scratch database and verify ------------------------
log "step 2/3: pg_restore into scratch database $DRILL_DB"
compose exec -T postgres dropdb --if-exists -U "$PGUSER" "$DRILL_DB"
compose exec -T postgres createdb -U "$PGUSER" "$DRILL_DB"
compose exec -T postgres pg_restore -U "$PGUSER" -d "$DRILL_DB" --no-owner --exit-on-error < "$newest_dump"

counts="$(compose exec -T postgres psql -U "$PGUSER" -d "$DRILL_DB" -tA -c \
  "SELECT (SELECT count(*) FROM posts) || ' ' || (SELECT count(*) FROM glossary)")"
posts_count="$(printf '%s' "$counts" | awk '{print $1}')"
glossary_count="$(printf '%s' "$counts" | awk '{print $2}')"
if [[ -z "$posts_count" || -z "$glossary_count" ]]; then
  die "row-count verification query failed on $DRILL_DB"
fi
log "verified scratch db: posts=$posts_count glossary=$glossary_count"
compose exec -T postgres dropdb -U "$PGUSER" "$DRILL_DB"
log "scratch database $DRILL_DB dropped"

# --- Step 3: media verification --------------------------------------------------
log "step 3/3: media file verification"
live_media_count="$(docker run --rm -v "$MEDIA_VOLUME:/media:ro" --entrypoint /bin/sh \
  restic/restic -c 'find /media -type f | wc -l' | tr -d '[:space:]')"
restored_media_count="$(find "$RESTORED_MEDIA" -type f 2>/dev/null | wc -l | tr -d ' ')"
log "live media files: $live_media_count; restored media files: $restored_media_count"
if [[ "$live_media_count" -gt 0 && "$restored_media_count" -lt 1 ]]; then
  die "live media volume has $live_media_count file(s) but none were restored"
fi
if [[ "$live_media_count" -eq 0 ]]; then
  log "media volume is empty; media restore check trivially satisfied"
fi

STATUS="PASS"
log "restore drill completed successfully"
