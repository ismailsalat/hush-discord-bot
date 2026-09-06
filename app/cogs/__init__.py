#: Loaded in order at startup. Error handling first so a failure in any later
#: extension still produces a friendly message.
EXTENSIONS = (
    "app.cogs.errors",
    "app.cogs.events",
    "app.cogs.confessions",
    "app.cogs.profiles",
    "app.cogs.discovery",
    "app.cogs.about",
    "app.cogs.moderation",
    "app.cogs.admin",
    "app.cogs.owner",
)
