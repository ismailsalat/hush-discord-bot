# Hush

**Anonymous confessions made simple.**

Hush lets communities share anonymous confessions, rate posts, follow anonymous
profiles, bookmark confessions, post updates and create polls, while keeping
public identities hidden.

Members DM the bot, accept the rules once, type a confession, preview it, and
post. It appears in your confession channel as `Anon #A17`.

---

## Features

- **Anonymous confessions** — DM → rules (once) → type → preview → post
- **Anonymous profiles** — per-server aliases with their own stats and followers
- **Ratings** — one button, 1–5, "how strongly did you react"
- **Followers** — follow an alias, get a DM when it posts again
- **Updates** — post a follow-up linked to an earlier confession
- **Bookmarks** — private saves, visible only to you
- **Polls** — added after posting, 2–4 options
- **Trending & Hall of Fame** — time-decayed scoring; three leaderboards, not twenty
- **Moderation** — reports, warnings, timed bans, append-only audit ledger
- **Permissions** — five tiers, with Hush Admins/Moderators set per server
- **Privacy** — aliases everywhere; owner-only, audited identity lookup
- **Operations** — verified backups, scoped exports, structured logs, health checks

A public confession shows exactly four buttons: **Rate · Profile · Follow · More**.
Everything else lives under More.

## Technology

| | |
|---|---|
| Language | Python 3.12+ |
| Discord | discord.py 2.x (app commands, persistent views, modals) |
| Database | PostgreSQL via SQLAlchemy 2.x async + asyncpg |
| Migrations | Alembic |
| Config | pydantic-settings |
| Logging | structlog |
| Tests | pytest + pytest-asyncio (SQLite) |
| Deploy | Railway, or Docker Compose |

---

## Commands

### Members

| Command | Does |
|---|---|
| `/confess` | Write and post an anonymous confession |
| `/profile` | View your anonymous profile, or another alias |
| `/bookmarks` | Confessions you saved (private) |
| `/following` | Anonymous profiles you follow |
| `/trending` | What is getting reactions right now |
| `/halloffame` | Highest rated, most rated, most discussed |
| `/about` | Version, uptime, servers, privacy summary |

### Moderators

| Command | Does |
|---|---|
| `/mod reports` | Work through the open report queue |
| `/mod review <number>` | Open the moderation panel for one confession |
| `/mod warn <anon_id> <reason>` | Issue a warning |
| `/mod ban <anon_id> <duration> <reason>` | Suspend Hush access (1h / 24h / 7d / 30d / permanent) |
| `/mod unban <anon_id>` | Restore access |
| `/mod history <anon_id>` | Warnings, bans and removals for an account |

### Admins

| Command | Does |
|---|---|
| `/admin setup` | Set the confession channel and optional mod log / roles |
| `/admin settings` | View or change settings (no options = view) |
| `/admin roles` | Grant or revoke Hush Admin / Moderator (**server owner only**) |
| `/admin status` | Live health, backup age, pending notices, errors, uptime |
| `/admin export` | Export this server's data |
| `/admin backup` | See whether backups are healthy |

### Bot owner

| Command | Does |
|---|---|
| `/owner status` | System-wide health and background task state |
| `/owner guilds` | Servers Hush is in, and which are configured |
| `/owner export` | Global exports, including the full database |
| `/owner backup` | Create, list, verify, restore-test |
| `/owner identity` | Resolve an alias to a person — audited, requires a reason |

---

## Permission levels

| Level | Who | Can |
|---|---|---|
| **Member** | everyone | confess, rate, follow, bookmark, report, vote in polls |
| **Hush Moderator** | configured role or user | everything above, plus reports, removals, warnings, bans, history |
| **Hush Admin** | configured role or user, or Discord Administrator | everything above, plus settings, channels, guild exports, status |
| **Server Owner** | the Discord guild owner | everything above, plus deciding who is a Hush Admin/Moderator |
| **Bot Owner** | listed in `BOT_OWNER_IDS` | system operations, global exports, backups, identity lookup |

A Hush Admin **cannot** promote anyone — only the server owner can change who
moderates. A Hush Admin does not need Discord Administrator, so you can delegate
Hush without handing over your server.

Set them up with:

```
/admin roles action:Grant level:Hush Moderator role:@Mods
/admin roles action:Grant level:Hush Admin  user:@Trusted
```

---

## Local setup

```bash
git clone <your-repo> hush && cd hush
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env      # fill in DISCORD_TOKEN and BOT_OWNER_IDS

alembic upgrade head
python -m app.main
```

SQLite works out of the box for development. Production requires PostgreSQL —
Hush refuses to start with `ENVIRONMENT=production` on SQLite, because that data
would be lost on redeploy.

### Discord application setup

1. Open <https://discord.com/developers/applications> → **New Application**
2. **Bot** → **Reset Token** → copy into `DISCORD_TOKEN`
3. **Privileged Gateway Intents: leave all three OFF.** Hush does not need them
   and cannot read your channel messages.
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: View Channels, Send Messages, Embed Links,
     Read Message History, Manage Messages
5. Invite the bot, then run `/admin setup` in your server.

### PostgreSQL

```bash
createdb hush
export DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/hush"
alembic upgrade head
```

The `+asyncpg` driver is required.

### Migrations

```bash
alembic upgrade head                      # apply
alembic downgrade -1                      # roll back one
alembic current                           # what is applied
alembic revision --autogenerate -m "..."  # after changing models
```

Hush also applies pending migrations at startup when
`RUN_MIGRATIONS_ON_START=true` (the default). If it is off and the schema is
behind, Hush refuses to start rather than running against an old schema.

### Tests

```bash
pytest              # 249 tests
pytest -q --tb=short
```

Tests run against a real SQLite schema, so constraints are genuinely exercised.
The Discord layer is faked behind a Protocol, so the full submission flow —
including its failure paths — is tested without a gateway connection.

### Docker

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f bot
```

Three services: `postgres`, a one-shot `migrate`, and `bot`, which starts only
after migrations succeed.

---

## Railway deployment

See [`docs/railway.md`](docs/railway.md) for the full walkthrough.

**Start command:** `python -m app.main`

Short version:

1. **New Project** → **Deploy from GitHub repo** → pick this repository
2. **+ New** → **Database** → **PostgreSQL**
3. In the bot service → **Variables**, set:
   - `DISCORD_TOKEN`
   - `BOT_OWNER_IDS`
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (then change `postgresql://`
     to `postgresql+asyncpg://`)
   - `ENVIRONMENT=production`, `LOG_JSON=true`
4. Add a **Volume** mounted at `/data` and set `BACKUP_DIRECTORY=/data/backups`
5. Deploy. Migrations run automatically at startup.
6. Confirm the bot is online, then run `/admin setup`.

---

## Environment variables

Full list with comments in [`.env.example`](.env.example).

| Variable | Required | Notes |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token |
| `BOT_OWNER_IDS` | yes | Comma-separated. The only place owner IDs are configured |
| `DATABASE_URL` | yes | `postgresql+asyncpg://…` in production |
| `ENVIRONMENT` | | `development` / `staging` / `production` |
| `LOG_LEVEL`, `LOG_JSON` | | `INFO`, and JSON logs in production |
| `RUN_MIGRATIONS_ON_START` | | Default `true` |
| `SUPPORT_SERVER_URL`, `GITHUB_URL`, `PRIVACY_POLICY_URL`, `TERMS_URL` | | `/about` buttons; hidden when unset |
| `BACKUP_DIRECTORY`, `EXPORT_DIRECTORY`, `LOG_DIRECTORY` | | Point backups at a persistent volume |
| `DEFAULT_CONFESSION_LIMIT`, `DEFAULT_ALIAS_ROTATION_DAYS` | | Defaults for new servers |
| `BRAND_NAME`, `BRAND_TAGLINE` | | Rename the product without touching code |

The version comes from `app/__version__.py`. `HUSH_VERSION` only overrides it.

---

## Backups

Hush verifies every backup it creates and can prove one restores without
touching production.

| Tier | Frequency | Retention |
|---|---|---|
| hourly | 1 hour | 48 hours |
| daily | 24 hours | 30 days |
| weekly | 7 days | 180 days |

```
/owner backup action:Create and verify
/owner backup action:Restore test (safe) name:<file>
```

```bash
python scripts/backup_database.py --tier daily --verify --prune
python scripts/verify_backup.py --latest --restore-test
```

There is deliberately **no** restore slash command — a real restore overwrites
production and is a documented host operation. See
[`docs/backup_restore.md`](docs/backup_restore.md).

## Exports

JSON, CSV, TXT and ZIP bundles. Scopes: guild, user, alias, confession,
moderation, reports, confessions-only, and full database (bot owner only).

Every export is ephemeral, expires after 24 hours, and is recorded with who ran
it and whether identities were redacted. Discord user IDs are stripped unless
the requester is the bot owner, and guild-wide exports never contain identities
at all.

---

## Project structure

```
app/
  cogs/          Discord commands - thin controllers only
  services/      Business logic, completely Discord-free
  database/
    models/      SQLAlchemy models
    repositories/  All SQL lives here
  views/         Buttons, dropdowns, persistent components
  modals/        Text-entry forms
  embeds/        Presentation - one design system
  tasks/         Background jobs and the scheduler
  security/      Permissions, identifiers, privacy, rate limiting
  exports/       JSON/CSV/TXT/ZIP writers
  backups/       Backup providers, manager, verifier
  utils/         Small shared helpers
  config/        Settings
  core/          Constants, exceptions, runtime container
migrations/      Alembic
scripts/         Operational CLI tools
docs/            Architecture, database, moderation, privacy, backups, deploy
tests/           249 tests
```

Cogs call services, services call repositories, repositories talk to the
database. Nothing skips a layer.

---

## Privacy

> Anonymous to regular server members. Hush privately retains account mappings
> for moderation, abuse prevention and system integrity.

Hush never claims users are untraceable.

- Members are anonymous **to each other**
- Moderators act on aliases and never see identities
- Only the bot owner can resolve an alias to a person, and every lookup requires
  a written reason and is recorded in the append-only ledger
- Rotating your anonymous ID is a real reset: followers do not transfer, and
  nothing publicly links the old and new identities
- Public button IDs cannot contain a Discord ID or internal user ID — the helper
  that builds them raises if you try

Hush requests **no privileged intents**.

---

## Documentation

| Document | Contents |
|---|---|
| [architecture.md](docs/architecture.md) | Layers, data flow, persistence |
| [database.md](docs/database.md) | Schema and design decisions |
| [moderation.md](docs/moderation.md) | Tools, tiers, the closed-DM guarantee |
| [privacy.md](docs/privacy.md) | Identity model and guarantees |
| [backup_restore.md](docs/backup_restore.md) | Backups, verification, restoring |
| [deployment.md](docs/deployment.md) | Docker and manual deployment |
| [railway.md](docs/railway.md) | Step-by-step Railway deployment |

## Licence

Provided as-is for you to deploy and modify.
