# Architecture

Hush is layered so that each layer has one job and can be reasoned about
(and tested) on its own.

```
Discord  →  cogs/  →  services/  →  repositories/  →  database
             ↑          │
          views/     embeds/
          modals/
```

## The layers

**`app/cogs/`** — thin controllers. A cog reads the interaction, calls one
service, and renders one embed. Cogs contain no SQL and no business rules. If a
cog is getting long, the logic belongs in a service.

**`app/services/`** — all business logic, and completely Discord-free. Services
take primitives and return DTOs, never `discord.py` objects. This is what makes
the test suite able to exercise the real rules without a gateway connection.

**`app/database/repositories/`** — all SQL. Every query lives in a repository
method with a name that says what it is for. Services never write queries.

**`app/embeds/`** — rendering only. Embed builders take DTOs, never ORM objects,
so a lazy-load can never fire during rendering and no embed can accidentally
reach a column it was not given.

**`app/views/` and `app/modals/`** — Discord components. They gate, call a
service, and render.

## Key objects

**`Runtime`** (`app/core/runtime.py`) holds settings, the database, embed
builders and rate limiters. One instance is attached to the bot and reached via
`interaction.client.runtime`. This is the alternative to module-level globals:
explicit, injectable, and easy to fake.

**`ConfessionPublisher`** (`app/services/publishing_service.py`) is a Protocol
implemented by `app/publisher.py`. The service layer publishes through the
protocol, so `PublishingService` is fully testable with a fake that records
calls instead of talking to Discord — see `tests/test_publishing.py`.

**`requires(...)`** (`app/services/permission_service.py`) is the single
permission gate for commands. It resolves the caller's tier from the bot-owner
list and the guild's configured Hush roles, defers the interaction so a slow
lookup cannot blow Discord's three-second deadline, and raises a friendly
`PermissionDeniedError` naming the tier the caller needed. No command contains
its own permission logic.

**`ensure_ready`** (`app/views/gate.py`) is the single gate every interaction
passes through. It applies, in order:

1. an outstanding moderation notice (replayed in-app)
2. an active ban
3. the rules agreement

Because there is exactly one gate, a new feature cannot forget a check, and
closing your DMs cannot make a notice disappear.

## Data flow of one confession

1. User opens a modal and types. Nothing is stored yet.
2. Preview is rendered. Still nothing stored.
3. **Post** → `PublishingService.submit()`:
   - Stage 1: validate, insert a `PENDING` row, **commit**.
   - Stage 2: post the Discord message.
   - Stage 3: record message ids, mark `POSTED`, clear the draft, **commit**.
4. Any failure at any stage saves the text as a draft and returns a short error
   id. A crash between stages 1 and 2 leaves a `PENDING` row, which the
   reconciliation task repairs on the next run or at startup.

The invariant: **the database and Discord never disagree.** Either the
confession is posted and recorded, or it is not posted and the text is safe.

## Persistence of components

Every button attached to a long-lived message is a `discord.ui.DynamicItem`
with a regex template, e.g. `cf:rate:(?P<cid>conf_[0-9a-f]{4,32})`. The subject
is carried in the custom id and parsed back on click, so no in-memory view state
survives a restart — the classes are simply re-registered at startup and old
buttons keep working.

`build_custom_id()` refuses to encode a Discord snowflake or an internal user
id. That is a deliberate tripwire: it makes a whole category of privacy leak
impossible to write by accident.

## File size

No module is a dumping ground. Services are one concern each; the largest
files are the export service and the admin cog, both of which are lists of
independent cases rather than tangled logic.
