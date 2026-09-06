"""The public confession embed - the most visible surface in the product.

Kept deliberately sparse: alias, number, the text, one rating line and two small
counters. Everything else lives behind the ``More`` menu.
"""

from __future__ import annotations

import discord

from app.embeds.factory import SEPARATOR, Colors, EmbedFactory, subtext
from app.services.dto import ConfessionView, PollView
from app.utils.text import neutralize_mentions, pluralize, progress_bar
from app.utils.time import discord_timestamp


class ConfessionEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def build(self, view: ConfessionView) -> discord.Embed:
        stats = view.stats

        lines: list[str] = [
            subtext(discord_timestamp(view.created_at, "f")),
            "",
            neutralize_mentions(view.content),
            "",
            SEPARATOR,
        ]

        if stats.rating_count:
            lines.append(
                f"**Rating:** {stats.rating_display} / {view.scale_max}"
                f"  \u00b7  {pluralize(stats.rating_count, 'rating')}"
            )
        else:
            lines.append("**Rating:** not yet rated")

        counters: list[str] = []
        if stats.reply_count:
            counters.append(f"\U0001f4ac {pluralize(stats.reply_count, 'reply', 'replies')}")
        if stats.bookmark_count:
            counters.append(f"\U0001f516 {pluralize(stats.bookmark_count, 'bookmark')}")
        if counters:
            lines.append(subtext("  \u00b7  ".join(counters)))

        embed = self.factory.base(
            title=f"{view.alias_display} \u2014 Confession #{view.public_number}",
            description="\n".join(lines),
            color=Colors.BRAND,
        )

        # An update points back to what it updates, and the original points
        # forward to its newest update. Both are separate, rateable posts.
        if view.is_update and view.parent_number is not None:
            embed.add_field(
                name=f"\u21a9 Update to Confession #{view.parent_number}",
                value=subtext("Use **More \u2192 View Original** to read the original."),
                inline=False,
            )
        if view.update_numbers:
            newest = view.update_numbers[-1]
            embed.add_field(
                name=f"\U0001f195 New update: Confession #{newest}",
                value=subtext("Use **More \u2192 View Updates** to follow the story."),
                inline=False,
            )

        return self.factory.with_anonymity_footer(embed)

    def poll(self, poll: PollView, *, alias_display: str, public_number: int) -> discord.Embed:
        """Poll results rendered as bars, attached to an existing confession."""
        lines: list[str] = [f"**{poll.question}**", ""]
        for option in poll.options:
            bar = progress_bar(option.percentage / 100)
            marker = " \u2190 your vote" if option.option_id == poll.voted_option_id else ""
            lines.append(f"`{bar}` **{option.label}**{marker}")
            lines.append(subtext(f"{option.percentage:.0f}% ({option.votes})"))
        lines.append("")
        lines.append(subtext(f"Total votes: {poll.total_votes}"))
        if poll.is_open:
            lines.append(subtext("You can still change your vote."))

        return self.factory.base(
            title=f"Poll \u00b7 {alias_display} \u2014 Confession #{public_number}",
            description="\n".join(lines),
            color=Colors.BRAND,
        )

    def preview(self, content: str, limit: int) -> discord.Embed:
        """Private preview shown before posting."""
        embed = self.factory.base(
            title="Preview your confession",
            description=(
                "This is how it will appear. You can still edit it.\n\n"
                f">>> {neutralize_mentions(content)}"
            ),
            color=Colors.BRAND,
        )
        embed.add_field(
            name="\u200b",
            value=subtext(f"Character count: {len(content):,} / {limit:,}"),
            inline=False,
        )
        return embed

    def draft_recovered(self, content: str, *, reason: str | None = None) -> discord.Embed:
        embed = self.factory.base(
            title="Your confession was saved",
            description=(
                "Posting did not go through, but nothing was lost.\n\n"
                f">>> {neutralize_mentions(content)}"
            ),
            color=Colors.WARNING,
        )
        if reason:
            embed.add_field(name="Reference", value=f"`{reason}`", inline=False)
        return embed

    def posted(self, view: ConfessionView) -> discord.Embed:
        embed = self.factory.success(
            "Confession posted",
            f"Your confession has been posted as **#{view.public_number}**.",
        )
        if view.message_link:
            embed.add_field(
                name="\u200b",
                value=f"[View confession #{view.public_number}]({view.message_link})",
                inline=False,
            )
        embed.add_field(
            name="\u200b",
            value=subtext("You can post an update to this later if you'd like."),
            inline=False,
        )
        return embed
