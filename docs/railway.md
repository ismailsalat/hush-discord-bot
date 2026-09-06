# Deploying Hush on Railway

Start command: **`python -m app.main`**

Railway's Nixpacks builder detects Python automatically. `railway.json` in the
repository root already sets the start command, so you normally do not have to
type it anywhere.

---

## 1. Create the project

1. Go to <https://railway.app> and sign in.
2. **New Project** → **Deploy from GitHub repo**.
3. Authorise Railway and pick your Hush repository.

Railway will start a first build. It will fail or crash-loop until you add the
variables below — that is expected, and the logs will tell you exactly what is
missing.

## 2. Add PostgreSQL

1. In the project, click **+ New** → **Database** → **Add PostgreSQL**.
2. Wait for it to provision.

Railway now exposes `${{Postgres.DATABASE_URL}}` to other services in the
project.

## 3. Add a volume for backups

Railway's container filesystem is **wiped on every deploy**. The database itself
lives in PostgreSQL and is safe, but local backup files are not.

1. Select the Hush service → **Settings** → **Volumes** → **New Volume**.
2. Mount path: `/data`.

Then set `BACKUP_DIRECTORY=/data/backups` in the variables below.

Exports do not need a volume — they are temporary by design and are cleaned up
after 24 hours.

## 4. Set environment variables

Select the Hush service → **Variables** → **Raw Editor**, and paste:

```
DISCORD_TOKEN=your-bot-token
BOT_OWNER_IDS=your-discord-id,another-owner-id
DATABASE_URL=${{Postgres.DATABASE_URL}}

ENVIRONMENT=production
LOG_LEVEL=INFO
LOG_JSON=true
RUN_MIGRATIONS_ON_START=true

BACKUP_DIRECTORY=/data/backups
EXPORT_DIRECTORY=/data/exports
LOG_DIRECTORY=/data/logs
```

### The one Railway gotcha

Railway's `DATABASE_URL` starts with `postgresql://`. Hush uses the async
driver and needs `postgresql+asyncpg://`.

Either edit the variable after referencing it:

```
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@HOST:PORT/railway
```

(copy the values from the Postgres service's **Connect** tab), or keep the
reference and let Hush normalise it — it accepts a plain `postgresql://` URL and
upgrades the driver at startup, logging a notice when it does.

### Optional variables

```
SUPPORT_SERVER_URL=https://discord.gg/yourserver
GITHUB_URL=https://github.com/you/hush
PRIVACY_POLICY_URL=https://yoursite.com/privacy
TERMS_URL=https://yoursite.com/terms
```

Each one adds a button to `/about`. Buttons for unset links are simply not
rendered.

## 5. Deploy

Railway redeploys automatically when variables change. Otherwise:
**Deployments** → **Deploy**.

## 6. Migrations

Nothing to do. With `RUN_MIGRATIONS_ON_START=true` (the default) Hush applies
pending migrations during startup, before it connects to Discord, and logs:

```
startup_step  step=2  stage=migrations  detail="upgraded empty -> 0002_hush_roles"
```

If you would rather run them yourself, set `RUN_MIGRATIONS_ON_START=false` and
use the Railway CLI:

```bash
railway run alembic upgrade head
```

With that setting off, Hush refuses to start when the schema is behind rather
than running against an old database.

## 7. Confirm it is online

In the **Deploy Logs** you should see, in order:

```
BOT_START            version=1.0.0
startup_step  step=1   stage=database        ok=True
startup_step  step=2   stage=migrations      detail=up to date (…)
startup_step  step=3   stage=guild_records
…
startup_step  step=13  stage=command_sync    commands=10
startup_step  step=14  stage=ready
```

Then in Discord:

1. The bot shows as online.
2. Run `/about` — it should report your server count and uptime.
3. Run `/admin setup confession_channel:#confessions`.
4. Run `/admin status` — everything should be green.

Global slash commands can take up to an hour to appear the first time.

---

## Troubleshooting

**"Hush cannot start. Fix the following:"** — the startup validator lists every
missing variable at once. Fix them all and redeploy.

**Crash loop with no message** — check `DATABASE_URL`. If the Postgres service
was added after the bot, the reference may not have resolved; re-enter it.

**Commands do not appear** — global commands propagate slowly. Confirm
`command_sync` in the logs shows a non-zero count.

**Backups say "no backups found"** — expected on a fresh deploy; the first
hourly backup runs five minutes after startup. If it persists, confirm the
volume is mounted and `BACKUP_DIRECTORY` points inside it.

**Bot restarts every few minutes** — check the deploy logs for a stack trace.
Hush shuts down cleanly on SIGTERM, so a healthy restart logs
`shutdown_complete`.

## What Railway restarts do

Hush handles redeploys safely:

- background tasks are cancelled and awaited, not abandoned
- database connections are disposed
- persistent buttons on old confessions keep working, because the confession id
  lives in the button's custom id rather than in memory
- a confession interrupted mid-post is repaired on the next startup and its text
  is preserved as a draft
- temporary bans that expired while offline are lifted during startup
