"""Rules agreement and the DM home screen."""

from __future__ import annotations

import discord

from app.embeds.factory import Colors, EmbedFactory, subtext

#: The prohibited-content list. Everything else is left to the server's own rules.
PROHIBITED_RULES: tuple[str, ...] = (
    "Self-harm or suicide content",
    "Encouragement or instructions involving self-harm",
    "Rape / sexual assault content",
    "Sexual content involving minors",
    "Credible threats toward real people",
    "Doxxing or private personal information",
    "Extremely graphic material",
    "Severe targeted harassment",
)

ALLOWED_NOTE = (
    "Dark humour, profanity, embarrassing stories, edgy jokes, relationship drama "
    "and controversial opinions are generally fine, as long as they stay within the "
    "rules above and your server's own rules."
)


class AgreementEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def rules(
        self, *, guild_name: str | None = None, version: int = 1, is_reacceptance: bool = False
    ) -> discord.Embed:
        brand = self.factory.brand
        title = (
            f"The {brand} rules have been updated"
            if is_reacceptance
            else f"Before you use {brand}"
        )
        intro = (
            "This server has updated its confession rules. Please review and accept them once more."
            if is_reacceptance
            else "By continuing, you agree not to submit content involving the following:"
        )

        rules = "\n".join(f"\u2022 {rule}" for rule in PROHIBITED_RULES)
        embed = self.factory.base(
            title=title,
            description=f"{intro}\n\n{rules}\n\n{ALLOWED_NOTE}",
            color=Colors.BRAND,
        )
        embed.add_field(
            name="\u2139 Your anonymity",
            value=subtext(self.factory.anonymity_line),
            inline=False,
        )
        footer = f"Rules version {version}"
        if guild_name:
            footer += f" \u00b7 {guild_name}"
        embed.set_footer(text=footer)
        return embed

    def accepted(self, guild_name: str | None = None) -> discord.Embed:
        where = f" in **{guild_name}**" if guild_name else ""
        return self.factory.success(
            "You're all set",
            f"You can now send anonymous confessions{where}. "
            "You won't be asked to accept these rules again unless they change.",
        )

    def cancelled(self) -> discord.Embed:
        return self.factory.base(
            title="No problem",
            description="You have not accepted the rules, so nothing was submitted. "
            "You can start again whenever you like.",
            color=Colors.MUTED,
        )

    def home(self, *, alias_display: str | None = None) -> discord.Embed:
        """The DM home screen. Minimal on purpose."""
        brand = self.factory.brand
        embed = self.factory.base(
            title=f"Welcome to {brand}",
            description=self.factory.tagline,
            color=Colors.BRAND,
        )
        embed.add_field(
            name="\U0001f4dd New Confession",
            value=subtext("Send something anonymously."),
            inline=False,
        )
        embed.add_field(
            name="\U0001f464 My Profile",
            value=subtext(
                f"Your anonymous profile{f' \u2014 {alias_display}' if alias_display else ''}."
            ),
            inline=False,
        )
        embed.add_field(
            name="\U0001f516 My Bookmarks",
            value=subtext("See your saved confessions."),
            inline=False,
        )
        return self.factory.with_anonymity_footer(embed)

    def submission_prompt(self, limit: int, *, guild_name: str | None = None) -> discord.Embed:
        where = f" to **{guild_name}**" if guild_name else ""
        embed = self.factory.base(
            title="Send your confession",
            description=f"Type your confession below and send it{where}.",
            color=Colors.BRAND,
        )
        embed.add_field(
            name="\u200b",
            value=subtext(f"Character limit: {limit:,}  \u00b7  You can edit it before posting."),
            inline=False,
        )
        return embed

    def alias_rotation_notice(
        self, *, current_alias: str, available_on: str | None, can_rotate: bool
    ) -> discord.Embed:
        embed = self.factory.base(
            title="Change your anonymous ID",
            description=(
                "Changing your anonymous ID creates a **new public identity**.\n\n"
                "\u2022 Your old profile will not publicly link to your new one\n"
                "\u2022 Your existing followers will not follow the new identity\n"
                "\u2022 Confessions you already posted stay under your old ID"
            ),
            color=Colors.WARNING if can_rotate else Colors.MUTED,
        )
        embed.add_field(name="Current", value=current_alias, inline=True)
        if not can_rotate and available_on:
            embed.add_field(name="Next rotation available", value=available_on, inline=True)
        return embed

    def alias_rotated(self, *, old_alias: str, new_alias: str) -> discord.Embed:
        embed = self.factory.success(
            "Your anonymous ID has changed",
            f"You are now **{new_alias}**.",
        )
        embed.add_field(
            name="\u200b",
            value=subtext(
                f"{old_alias} keeps its own public profile and followers. "
                "Nothing publicly connects the two."
            ),
            inline=False,
        )
        return embed
