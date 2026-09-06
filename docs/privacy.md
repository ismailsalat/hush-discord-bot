# Privacy model

## What Hush promises

> Anonymous to server members. Hush retains account information for
> moderation and abuse prevention.

That exact wording appears on public embeds and in the rules screen. Hush
never claims total anonymity, because that would be a lie: the bot has to know
who submitted what in order to enforce bans and handle abuse.

## Layers of identity

| Layer | Example | Who sees it |
|---|---|---|
| Discord user id | `123456789012345678` | Bot owner only, via an audited lookup |
| Internal user id | `usr_4f1a…` | Never shown publicly; used internally to link accounts |
| Public alias | `Anon #A17` | Everyone |

Moderators act on the public alias. Server owners and Hush Admins cannot see
identities either - only the bot owner can, and only through an audited lookup.

The Discord user id is **never** used as a public identity, never rendered in
an embed, and never placed in a component custom id.

## The custom-id tripwire

`app/security/identifiers.py::build_custom_id()` raises `ValueError` if asked to
encode anything matching an internal user id prefix or a 17–20 digit snowflake.
Every public button is built through it. `tests/test_security.py` asserts this.

## Alias rotation is a real privacy reset

Rotating an anonymous ID is not a rename:

- the old alias keeps its own profile, confessions and followers
- the new alias starts empty
- **followers do not transfer** — this is the point, and is enforced and tested
- nothing publicly links the two

Internally both aliases still map to the same internal user id, so moderation
history survives rotation. A retired alias body is never reissued to anyone
else, so nobody can inherit another person's reputation.

A database-level partial unique index guarantees a user can only ever have one
*current* alias per guild.

## Moderator visibility

Moderators act on aliases. The moderation panel, account history and mod log all
show `Anon #A17` and never a Discord identity.

The single exception is `/owner identity`, which:

- requires `BOT_OWNER` (not a server owner, admin or moderator)
- refuses to run without a written reason
- writes an `IDENTITY_LOOKUP` row to the append-only ledger *and* a security log
  entry before returning anything

## Export redaction

`discord_user_id` and `requested_by_discord_id` are stripped from every export
unless the requester is the bot owner. Guild-wide exports never carry identity
data at all, even for the owner — a whole-server dump stays alias-only. Every
export is recorded with who ran it, what scope, and whether it was redacted.

## Intents

The bot requests `guilds`, `guild_messages` and `dm_messages`. It does **not**
request `message_content` or `members`. Confessions are typed into modals, and
reply counting reads only `message.reference`. Hush never reads what
members write in your channels.

## Data retention

- Confessions are soft-deleted: hidden immediately, retained for moderation.
- Drafts expire after 30 minutes (configurable).
- Export files are deleted automatically after 24 hours.
- Backups follow 48h / 30d / 180d retention by tier.
