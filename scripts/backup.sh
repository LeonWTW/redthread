#!/usr/bin/env bash
# RedThread nightly backup (M2 task 2.6 — BLOCKING GATE).
#
# What it does:
#   1. pg_dump (custom format) from the postgres container into ./backups/,
#      keeping the last 3 local dumps.
#   2. restic backup of ./backups + the media volume, via the restic/restic
#      docker image (no host restic install needed).
#   3. restic retention: --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune.
#
# Backup target is selected purely by env:
#   RESTIC_REPOSITORY=/abs/path/to/repo          -> local repository (drill)
#   RESTIC_REPOSITORY=b2:$B2_BUCKET:redthread    -> Backblaze B2 (production)
# For B2, restic reads B2_ACCOUNT_ID / B2_ACCOUNT_KEY; this script maps them
# from B2_KEY_ID / B2_APP_KEY when not set explicitly.
#
# Runs on the VPS via cron (see docs/runbook.md). Exits non-zero on ANY
# failure so cron surfaces it.

set -euo pipefail

log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${BACKUP_ENV_FILE:-$COMPOSE_DIR/.env}"
BACKUP_DIR="$COMPOSE_DIR/backups"
KEEP_LOCAL_DUMPS=3

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

# Map the B2 credential names restic expects from our .env names.
export B2_ACCOUNT_ID="${B2_ACCOUNT_ID:-${B2_KEY_ID:-}}"
export B2_ACCOUNT_KEY="${B2_ACCOUNT_KEY:-${B2_APP_KEY:-}}"

if [[ -z "${RESTIC_REPOSITORY:-}" ]]; then
  die "RESTIC_REPOSITORY is unset. Set it in $ENV_FILE (local path for drills, b2:<bucket>:redthread for production)."
fi
if [[ -z "${RESTIC_PASSWORD:-}" ]]; then
  die "RESTIC_PASSWORD is unset. Set it in $ENV_FILE; without it the restic repository cannot be opened."
fi
export RESTIC_REPOSITORY RESTIC_PASSWORD

# --- Step 1: pg_dump ----------------------------------------------------------
mkdir -p "$BACKUP_DIR"
DUMP_FILE="$BACKUP_DIR/redthread-$(date -u +%Y%m%d-%H%M%S).dump"
log "step 1/3: pg_dump -> $DUMP_FILE"
(cd "$COMPOSE_DIR" && docker compose exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-redthread}" -d "${POSTGRES_DB:-redthread}" --format=custom) > "$DUMP_FILE"
if [[ ! -s "$DUMP_FILE" ]]; then
  die "pg_dump produced an empty file: $DUMP_FILE"
fi
log "pg_dump ok ($(wc -c < "$DUMP_FILE" | tr -d ' ') bytes)"

# Keep only the newest $KEEP_LOCAL_DUMPS local dumps.
old_dumps="$(ls -1t "$BACKUP_DIR"/redthread-*.dump | tail -n +$((KEEP_LOCAL_DUMPS + 1)) || true)"
if [[ -n "$old_dumps" ]]; then
  while IFS= read -r f; do
    log "pruning old local dump: $f"
    rm -f "$f"
  done <<< "$old_dumps"
fi

# --- Step 2: restic backup (via restic/restic docker image) --------------------
PROJECT_NAME="$(printf '%s' "${COMPOSE_PROJECT_NAME:-$(basename "$COMPOSE_DIR")}" | tr '[:upper:]' '[:lower:]')"
MEDIA_VOLUME="${PROJECT_NAME}_mediadata"

# Host ./backups is mounted at /host/backups and the dumps are staged into
# /data/backups (container-local) with cp before restic reads them. Reason:
# restic opens source files with O_NOATIME, which Docker Desktop's macOS file
# sharing rejects with EIO on read; plain cp reads are fine. Named volumes
# (media) are VM-native and unaffected. On the Linux VPS the cp is a cheap
# no-op-equivalent, keeping a single code path and stable snapshot paths
# (/data/backups, /data/media).
RESTIC_DOCKER_ARGS=(
  --rm
  -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e B2_ACCOUNT_ID -e B2_ACCOUNT_KEY
  -v "$BACKUP_DIR:/host/backups:ro"
  -v "$MEDIA_VOLUME:/data/media:ro"
)
# A local repository (absolute path) must be mounted into the container at the
# same path so the RESTIC_REPOSITORY value resolves inside it.
if [[ "$RESTIC_REPOSITORY" == /* ]]; then
  mkdir -p "$RESTIC_REPOSITORY"
  RESTIC_DOCKER_ARGS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi

restic_run() { docker run "${RESTIC_DOCKER_ARGS[@]}" restic/restic "$@"; }

log "step 2/3: restic backup -> $RESTIC_REPOSITORY (media volume: $MEDIA_VOLUME)"
if ! restic_run snapshots > /dev/null 2>&1; then
  log "repository not initialized (or unreachable); attempting restic init"
  restic_run init
fi

# Only redthread-*.dump files are staged, so a local repository living inside
# ./backups is never backed up into itself.
docker run "${RESTIC_DOCKER_ARGS[@]}" --entrypoint /bin/sh restic/restic -c \
  'mkdir -p /data/backups && cp /host/backups/redthread-*.dump /data/backups/ &&
   restic backup --host redthread --tag nightly /data/backups /data/media'
log "restic backup ok"

# --- Step 3: retention ----------------------------------------------------------
log "step 3/3: restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune"
restic_run forget --host redthread --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
log "backup complete"
