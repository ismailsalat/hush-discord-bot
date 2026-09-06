# Backup and restore

## Design

A backup that has never been opened is not a backup. Hush verifies every
backup it creates, and can prove one restores without touching production.

- **SQLite**: `VACUUM INTO` — a consistent snapshot taken while the bot runs.
- **PostgreSQL**: `pg_dump`.

Both are gzipped and stored through a `BackupProvider`. Only
`LocalBackupProvider` ships today; adding S3 is a new class implementing five
methods, not a refactor.

## Schedule and retention

| Tier | Frequency | Kept for |
|---|---|---|
| hourly | every hour | 48 hours |
| daily | every 24 hours | 30 days |
| weekly | every 7 days | 180 days |

Retention is applied by the weekly job. All three windows are configurable.

## Verification

Each backup gets a SHA-256 sidecar at creation. Verification then:

1. confirms the archive exists
2. re-hashes it and compares against the recorded digest
3. decompresses it
4. runs `PRAGMA integrity_check`
5. runs `PRAGMA foreign_key_check`
6. confirms every critical table is present
7. reads a row count from every table

A corrupted archive fails at step 2 or 3 — never silently passes. This is
covered by `tests/test_backups.py::TestVerification::test_corruption_is_detected`.

## Restore testing

`restore_test()` decompresses into a temporary directory, opens it, and counts
tables. **It never touches the live database** — the restore target is always a
throwaway file that is deleted afterwards, which is asserted in the tests.

## Commands

```bash
# In Discord (owner only)
/backup create
/backup list
/backup verify <name>

# On the host
python scripts/backup_database.py --tier daily --verify --prune
python scripts/verify_backup.py --latest --restore-test
python scripts/verify_backup.py --all
```

## Restoring for real

SQLite:

```bash
docker compose stop bot
gunzip -c backups/hush-daily-YYYYMMDD-HHMMSS.sqlite.gz > hush.sqlite3
docker compose start bot
```

PostgreSQL:

```bash
docker compose stop bot
gunzip -c backups/hush-daily-YYYYMMDD-HHMMSS.sql.gz \
  | docker compose exec -T postgres psql -U hush -d hush
docker compose start bot
```

Verify the archive **before** overwriting anything:

```bash
python scripts/verify_backup.py --name <file> --restore-test
```

On startup the bot reconciles any confession left mid-post, so a restore does
not leave ghost rows.
