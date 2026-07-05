# RedThread Runbook

## Backup (M2 blocking gate — live before daily clipping)

`scripts/backup.sh` protects the corpus (database + media). It:

1. Runs `pg_dump --format=custom` inside the postgres container and writes it
   to `./backups/redthread-YYYYMMDD-HHMMSS.dump` (UTC timestamp). The newest
   3 local dumps are kept; older ones are deleted.
2. Takes a restic snapshot of `./backups` (the dumps) plus the `mediadata`
   docker volume, using the `restic/restic` docker image — no host restic
   install. The repository is auto-initialized on first run.
3. Applies retention: `restic forget --keep-daily 7 --keep-weekly 4
   --keep-monthly 6 --prune`.

It exits non-zero on any failure so cron surfaces it, and logs each step with
UTC timestamps.

### Configuration (all via `.env` in the compose directory)

- `RESTIC_REPOSITORY` — backup target, selected purely by env:
  - Local repository (drills / before B2 exists): an absolute path, e.g.
    `/absolute/path/to/backups/restic-repo-local-test`.
  - Backblaze B2 (production): `b2:$B2_BUCKET:redthread`. restic reads the
    credentials as `B2_ACCOUNT_ID=$B2_KEY_ID` / `B2_ACCOUNT_KEY=$B2_APP_KEY`;
    the script maps them automatically from the `B2_*` values in `.env`.
- `RESTIC_PASSWORD` — repository encryption password. Losing it means losing
  the backups; keep an off-VPS copy in a password manager.
- `BACKUP_ENV_FILE` — optional override for the `.env` location.
- Variables already exported by the caller take precedence over `.env`.

The script fails loudly (non-zero exit, clear message) when
`RESTIC_REPOSITORY` or `RESTIC_PASSWORD` is unset.

### Nightly cron (on the Hetzner VPS)

Run as the deploy user that owns the compose stack, 03:30 UTC nightly, with
`flock` so overlapping runs are impossible:

```
30 3 * * * flock -n /var/lock/redthread-backup.lock /opt/redthread/scripts/backup.sh >> /var/log/redthread/backup.log 2>&1
```

Adjust `/opt/redthread` to the compose directory on the VPS and make sure
`/var/log/redthread/` exists. A non-zero exit is reported by cron mail (or
check the log tail after 03:30 UTC).

## Restore drill (monthly)

Run `scripts/restore_drill.sh` on the first weekend of every month. It never
touches the live database or media volume. It:

1. Restores the **latest** restic snapshot to a temp dir under `./backups/`
   (via the `restic/restic` image).
2. `pg_restore`s the newest restored dump into a scratch database
   `redthread_drill`, verifies it with a row-count query on `posts` and
   `glossary`, then drops the scratch database (also on failure, via trap).
3. Verifies that at least one media file was restored whenever the live media
   volume contains any files.
4. Prints `=== RESTORE DRILL: PASS ===` (exit 0) or `FAIL` (non-zero).

Procedure:

```bash
cd /opt/redthread            # compose directory (repo root)
./scripts/restore_drill.sh   # uses RESTIC_REPOSITORY/RESTIC_PASSWORD from .env
```

Expected: `PASS` summary, plausible row counts (posts should be non-zero once
daily clipping has started), exit code 0. On FAIL: treat backups as broken —
fix before the next clipping session, then re-run the drill. Append a row to
the drill log below after every drill.

### Drill log

| Date | Result | Notes |
|------|--------|-------|
| 2026-07-05 | PASS | First drill, local repo (`backups/restic-repo-local-test`), snapshot `42512a08`; restored newest dump; scratch db verified (posts=0, glossary=12) and dropped; media volume empty so media check trivially satisfied. |

## Service recovery

- After ANY server code change: `docker compose restart api worker` — the
  containers volume-mount the code but load it at process start (gunicorn and
  celery do not auto-reload).

_More to be documented as services land: re-running a stuck pipeline step,
rebuilding the Qdrant index via re-embed._
