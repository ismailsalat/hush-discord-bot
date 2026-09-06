# Deployment

Deploying on Railway? See [railway.md](railway.md) for the step-by-step guide.
This document covers Docker and manual deployment.

## Requirements

Python 3.12+, PostgreSQL 14+ (SQLite is fine for development),
`postgresql-client` for `pg_dump` if you use Postgres backups.

## Docker (recommended)

```bash
cp .env.example .env      # fill in DISCORD_TOKEN, BOT_OWNER_IDS, POSTGRES_PASSWORD
docker compose up -d
docker compose logs -f bot
```

The stack is three services: `postgres`, a one-shot `migrate` that runs
`alembic upgrade head`, and `bot`, which only starts once migrations succeed.
Both `postgres` and `bot` have health checks; `bot`'s runs
`scripts/health_check.py`.

## Manual

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python -m app.main
```

## Discord setup

1. https://discord.com/developers/applications → **New Application**
2. **Bot** → **Reset Token** → copy into `DISCORD_TOKEN`
3. Privileged intents: **leave all off.** Hush does not need them.
4. **OAuth2 → URL Generator**: scopes `bot` and `applications.commands`;
   permissions *View Channels*, *Send Messages*, *Embed Links*,
   *Read Message History*, *Manage Messages*.
5. Invite the bot, then in your server run:
   - `/admin setup confession_channel:#confessions mod_log:#mod-log`
   - `/admin roles action:Grant level:Hush Moderator role:@Moderator`
   - `/admin status` to confirm everything is green

Slash commands sync at startup and can take up to an hour to appear globally the
first time.

## Environment variables

See `.env.example`. The ones that matter most:

| Variable | Notes |
|---|---|
| `DISCORD_TOKEN` | Required |
| `BOT_OWNER_IDS` | Comma-separated. Grants backups, full exports, identity lookup. |
| `DATABASE_URL` | `postgresql+asyncpg://…` in production |
| `BRAND_NAME` / `BRAND_TAGLINE` | Rename the whole product without touching code |
| `LOG_JSON` | `true` in production for structured logs |

## Operating

```bash
docker compose logs -f bot                    # logs
python scripts/health_check.py                # health (exit 0 = healthy)
# or, in Discord: /admin status  and  /owner status
python scripts/verify_backup.py --latest      # backup confidence
```

Four log streams are written: `hush.app`, `hush.security`,
`hush.moderation`, `hush.metrics`. Secrets are redacted before
anything is written.

When a user reports an error, ask for the `ERR-XXXXX` code — it appears in the
application log alongside the full stack trace.

## Upgrading

```bash
git pull
docker compose build
docker compose up -d      # migrate runs automatically before bot restarts
```

Take a backup first: `python scripts/backup_database.py --tier manual --verify`.
