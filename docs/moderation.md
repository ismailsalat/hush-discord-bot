# Moderation

## Philosophy

Hush is not an aggressive AI moderation system. It does not scan, score or
auto-delete confessions. Reports are a signal; **humans decide.** Dark humour,
profanity and edgy content are allowed. The prohibited list is short and
specific, and is shown to every user before their first confession.

## Prohibited content

Self-harm or suicide content · encouragement or instructions for self-harm ·
rape and sexual assault content · sexual content involving minors · credible
threats · doxxing · extremely graphic material · severe targeted harassment.

## A Hush ban is not a Discord ban

Suspending someone removes their access to anonymous features. It does not
touch their Discord membership, and the notice they receive says so explicitly.

## Moderator tools

| Command | Purpose |
|---|---|
| `/mod reports` | Work through the open report queue |
| `/mod review <number>` | Open the moderation panel for one confession |
| `/mod warn <anon_id> <reason>` | Issue a warning |
| `/mod ban <anon_id> <duration> <reason>` | Suspend Hush access |
| `/mod unban <anon_id>` | Restore access |
| `/mod history <anon_id>` | Warnings, bans and removals for an account |

The panel offers: **Remove**, **Warn Author**, **Ban Author**, **Account
History**. Every destructive action asks for a reason first.

Ban durations are fixed choices — 1 hour, 24 hours, 7 days, 30 days, permanent —
so there is no free-form input to get wrong.

## Notices always arrive

Warnings and bans are **queued**, never delivered inline. This matters: a
moderator's action must not fail because the recipient has closed DMs.

The dispatcher retries delivery with a widening backoff (immediate, 15 minutes,
60 minutes) up to three attempts. If it never gets through, the notice stays
outstanding and is **replayed inside the app** the next time that user touches
anything Hush. Warnings require an explicit acknowledgement.

This is the closed-DM guarantee, and it is tested in
`tests/test_moderation.py::TestClosedDmGuarantee`.

## The ledger

`moderation_ledger` is append-only. Every action writes a row: what happened,
who did it, when, why, and the previous state where relevant. Nothing is ever
updated or deleted. Identity lookups appear here too.

## Permission tiers

`Member` → `Hush Moderator` → `Hush Admin` → `Server Owner` → `Bot Owner`.

- **Hush Moderator**: a role or user the server owner configured. Reports,
  removals, warnings, bans, history.
- **Hush Admin**: a configured role or user, or anyone with Discord
  Administrator. Everything a moderator can do, plus settings, channels, guild
  exports and status.
- **Server Owner**: the Discord guild owner. Additionally decides *who* is a
  Hush Admin or Moderator - an admin cannot promote themselves.
- **Bot Owner**: listed in `BOT_OWNER_IDS`. Backups, full exports, identity
  lookup, system operations.

Configure the middle two with `/admin roles`:

```
/admin roles action:Grant level:Hush Moderator role:@Mods
/admin roles action:Grant level:Hush Admin  user:@Trusted
```

Both roles and individual users are supported, so a small server does not have
to create a role for one person. A Hush Admin never needs Discord Administrator.

Every check in the codebase resolves through `security/permissions.py` and the
`requires(...)` decorator in `services/permission_service.py`. No command
re-implements a check.
