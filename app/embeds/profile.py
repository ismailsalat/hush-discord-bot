"""Anonymous profile, bookmark list, trending and hall of fame embeds."""

from __future__ import annotations

import discord

from app.embeds.factory import Colors, EmbedFactory, subtext
from app.services.dto import HallOfFame, ProfileView, TrendingEntry
from app.utils.pagination import Page


class ProfileEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def build(self, profile: ProfileView, *, own_profile: bool = False) -> discord.Embed:
        embed = self.factory.base(
            title=profile.alias_display,
            description=subtext(
                "Your anonymous profile" if own_profile else "Anonymous profile"
            ),
            color=Colors.BRAND,
        )
        embed.add_field(name="Confessions", value=str(profile.confession_count), inline=True)
        embed.add_field(name="Average Rating", value=profile.rating_display, inline=True)
        embed.add_field(name="Followers", value=str(profile.follower_count), inline=True)

        if profile.most_rated_number is not None:
            embed.add_field(
                name="Most Rated Confession",
                value=f"#{profile.most_rated_number} "
                f"({profile.most_rated_rating_count} ratings)",
                inline=False,
            )

        if profile.recent:
            lines = [
                f"**#{number}** \u00b7 {preview}" for number, preview in profile.recent
            ]
            embed.add_field(name="Recent Confessions", value="\n".join(lines), inline=False)
        else:
            embed.add_field(
                name="Recent Confessions",
                value=subtext("No confessions posted under this identity yet."),
                inline=False,
            )

        if not profile.is_current:
            embed.add_field(
                name="\u200b",
                value=subtext("This is a retired anonymous identity."),
                inline=False,
            )
        return self.factory.with_anonymity_footer(embed)

    def confession_list(
        self, alias_display: str, page: Page, *, title: str = "Confessions"
    ) -> discord.Embed:
        lines = [f"**#{number}** \u00b7 {preview}" for number, preview in page.items] or [
            subtext("Nothing here yet.")
        ]
        embed = self.factory.base(
            title=f"{alias_display} \u2014 {title}",
            description="\n".join(lines),
            color=Colors.BRAND,
        )
        embed.set_footer(text=f"{page.label} \u00b7 {page.total_items} total")
        return embed

    def bookmarks(self, page: Page) -> discord.Embed:
        if page.items:
            lines = [
                f"\U0001f516 **#{number}** \u00b7 {alias}\n{subtext(preview)}"
                for number, alias, preview, _cid in page.items
            ]
            description = "Here are the confessions you've saved.\n\n" + "\n".join(lines)
        else:
            description = "You have not saved any confessions yet."

        embed = self.factory.base(
            title="Your bookmarks", description=description, color=Colors.INFO
        )
        embed.set_footer(text=f"Only visible to you \u00b7 {page.label}")
        return embed

    def following(self, rows: list[tuple[str, bool]]) -> discord.Embed:
        if rows:
            lines = [
                f"\u2022 **{alias}**" + ("" if active else subtext(" (retired identity)"))
                for alias, active in rows
            ]
            description = "\n".join(lines)
        else:
            description = "You are not following anyone yet."
        embed = self.factory.base(
            title="Following", description=description, color=Colors.INFO
        )
        embed.set_footer(text="Only visible to you")
        return embed

    def trending(self, entries: list[TrendingEntry], *, window_hours: int = 24) -> discord.Embed:
        if not entries:
            return self.factory.base(
                title="Trending confessions",
                description="Nothing is trending yet. Rate a few confessions to get things moving.",
                color=Colors.BRAND,
            )

        lines: list[str] = []
        for entry in entries:
            rating = f"\u2b50 {entry.average_rating:.1f}" if entry.average_rating else "\u2b50 \u2014"
            lines.append(
                f"**#{entry.public_number}** \u2014 {entry.alias_display}\n"
                f"{subtext(entry.preview)}\n"
                f"{subtext(f'{rating}  \u00b7  {entry.rating_count} ratings  \u00b7  \U0001f4ac {entry.reply_count}')}"
            )

        embed = self.factory.base(
            title="Trending confessions",
            description=f"Top confessions from the last {window_hours} hours.\n\n"
            + "\n\n".join(lines),
            color=Colors.BRAND,
        )
        return self.factory.with_anonymity_footer(embed)

    def hall_of_fame(self, hall: HallOfFame) -> discord.Embed:
        embed = self.factory.base(
            title="Hall of Fame",
            description="The most memorable confessions of all time.",
            color=Colors.GOLD,
        )

        def render(entries) -> str:
            if not entries:
                return subtext("Nothing here yet.")
            return "\n".join(
                f"**#{entry.public_number}** \u2014 {entry.alias_display}\n"
                f"{subtext(entry.primary_metric)}"
                for entry in entries
            )

        embed.add_field(name="\u2b50 Highest Rated", value=render(hall.highest_rated), inline=False)
        embed.add_field(name="\U0001f4ca Most Rated", value=render(hall.most_rated), inline=False)
        embed.add_field(
            name="\U0001f4ac Most Discussed", value=render(hall.most_discussed), inline=False
        )
        return self.factory.with_anonymity_footer(embed)
