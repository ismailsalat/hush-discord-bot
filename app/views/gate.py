"""The interaction gate.

Every button, command and DM passes through :func:`ensure_ready`, which applies
the same three checks in the same order and, crucially, *shows the right UI* for
each outcome instead of a bare error:

* an undelivered moderation notice is replayed and must be seen
* a banned user is told, with duration and reason
* a first-time or out-of-date user is shown the rules to accept

Because it lives in one place, closing your DMs cannot skip a notice, and no
new feature can accidentally forget the checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

from app.core.constants import NotificationKind
from app.services.access_service import AccessService
from app.services.user_service import UserContext, UserService
from app.utils.time import ensure_utc
from app.views.common import respond, runtime_of


@dataclass(frozen=True, slots=True)
class Actor:
    """A caller that has passed every gate."""

    internal_id: str
    discord_user_id: int
    guild_id: int
    settings: object


async def resolve_actor(
    interaction: discord.Interaction, guild_id: int
) -> UserContext:
    """Resolve the Discord user into an internal identity."""
    runtime = runtime_of(interaction)
    async with runtime.session() as session:
        service = UserService(session, runtime.settings)
        return await service.resolve(interaction.user.id, guild_id)


async def ensure_ready(
    interaction: discord.Interaction,
    guild_id: int,
    *,
    require_agreement: bool = False,
    defer: bool = True,
    ephemeral: bool = True,
) -> Actor | None:
    """Gate an interaction.

    Returns an :class:`Actor` when the caller may proceed, or ``None`` after
    having already responded with the appropriate screen.
    """
    runtime = runtime_of(interaction)
    guild = interaction.guild or interaction.client.get_guild(guild_id)

    if defer and not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral, thinking=False)

    async with runtime.session() as session:
        user_service = UserService(session, runtime.settings)
        context = await user_service.resolve(interaction.user.id, guild_id)
        access = AccessService(session, runtime.settings)
        decision = await access.check(
            internal_user_id=context.internal_id,
            guild_id=guild_id,
            require_agreement=require_agreement,
        )

    # 1. A pending moderation notice always comes first.
    if decision.blocking_notice is not None:
        await _show_blocking_notice(interaction, decision.blocking_notice)
        return None

    # 2. Bans.
    if decision.ban_reason is not None:
        async with runtime.session() as session:
            ban = await AccessService(session, runtime.settings).active_ban(
                context.internal_id, guild_id
            )
        embed = runtime.moderation_embeds.ban_notice(
            duration="Permanent" if (ban and ban.is_permanent) else "Temporary",
            reason=(ban.reason if ban else decision.ban_reason) or "Not specified",
            guild_name=guild.name if guild else None,
            expires_at=ensure_utc(ban.expires_at) if ban and not ban.is_permanent else None,
        )
        await respond(interaction, embed=embed)
        return None

    # 3. Rules agreement.
    if decision.needs_agreement:
        from app.views.agreement import AgreementView

        settings = decision.settings
        embed = runtime.agreement_embeds.rules(
            guild_name=guild.name if guild else None,
            version=settings.rules_version if settings else 1,
            is_reacceptance=decision.is_reacceptance,
        )
        await respond(
            interaction,
            embed=embed,
            view=AgreementView(guild_id=guild_id, version=settings.rules_version if settings else 1),
        )
        return None

    return Actor(
        internal_id=context.internal_id,
        discord_user_id=interaction.user.id,
        guild_id=guild_id,
        settings=decision.settings,
    )


async def _show_blocking_notice(
    interaction: discord.Interaction, notification
) -> None:
    """Replay an undelivered warning or ban inside the app."""
    from app.views.notices import NoticeAcknowledgeView

    runtime = runtime_of(interaction)
    payload = notification.payload or {}

    if notification.kind == NotificationKind.WARNING:
        notice = runtime.moderation_embeds.warning_notice(
            reason=payload.get("reason", "Not specified"),
            guild_name=payload.get("guild_name"),
        )
    elif notification.kind == NotificationKind.BAN:
        expires_raw = payload.get("expires_at")
        expires_at = None
        if expires_raw:
            from datetime import datetime

            try:
                expires_at = ensure_utc(datetime.fromisoformat(expires_raw))
            except ValueError:
                expires_at = None
        notice = runtime.moderation_embeds.ban_notice(
            duration=payload.get("duration", "Unknown"),
            reason=payload.get("reason", "Not specified"),
            guild_name=payload.get("guild_name"),
            expires_at=expires_at,
        )
    else:  # pragma: no cover - only warnings and bans block
        notice = runtime.moderation_embeds.pending_notice_intro()

    view = (
        NoticeAcknowledgeView(notification.id)
        if notification.requires_acknowledgement and notification.acknowledged_at is None
        else None
    )

    # Mark shown even if acknowledgement is still outstanding: the user has now
    # definitely seen it, which is what the closed-DM requirement is about.
    async with runtime.session() as session:
        from app.services.notification_service import NotificationService

        await NotificationService(session).mark_shown(notification.id)

    await respond(
        interaction,
        embeds=[runtime.moderation_embeds.pending_notice_intro(), notice],
        view=view,
    )
