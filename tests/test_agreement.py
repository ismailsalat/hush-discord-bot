"""First-time agreement and re-acceptance on a rules version bump."""

from __future__ import annotations

import pytest

from app.core.exceptions import AgreementRequiredError
from app.database.repositories import GuildRepository
from app.services.access_service import AccessService
from app.services.agreement_service import AgreementService
from tests.conftest import GUILD_ID


class TestAgreement:
    async def test_new_user_has_not_accepted(self, session, factory):
        user = await factory.user()
        assert not await AgreementService(session).has_accepted(user.id, GUILD_ID, 1)

    async def test_acceptance_is_recorded(self, session, factory):
        user = await factory.user()
        service = AgreementService(session)
        await service.accept(user.id, GUILD_ID, 1)
        assert await service.has_accepted(user.id, GUILD_ID, 1)

    async def test_accepting_twice_is_harmless(self, session, factory):
        user = await factory.user()
        service = AgreementService(session)
        await service.accept(user.id, GUILD_ID, 1)
        await service.accept(user.id, GUILD_ID, 1)
        assert await service.has_accepted(user.id, GUILD_ID, 1)

    async def test_version_bump_requires_reacceptance(self, session, factory):
        user = await factory.user()
        service = AgreementService(session)
        await service.accept(user.id, GUILD_ID, 1)
        assert not await service.has_accepted(user.id, GUILD_ID, 2)

    async def test_reacceptance_restores_access(self, session, factory):
        user = await factory.user()
        service = AgreementService(session)
        await service.accept(user.id, GUILD_ID, 1)
        await service.accept(user.id, GUILD_ID, 2)
        assert await service.has_accepted(user.id, GUILD_ID, 2)


class TestAccessGate:
    async def test_submission_requires_agreement(self, session, settings, factory):
        user = await factory.user()
        with pytest.raises(AgreementRequiredError):
            await AccessService(session, settings).enforce(
                internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=True
            )

    async def test_engagement_does_not_require_agreement(self, session, settings, factory):
        """Rating someone else's confession shouldn't demand a rules screen."""
        user = await factory.user()
        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=False
        )
        assert decision.allowed

    async def test_bumping_rules_version_gates_existing_members(
        self, session, settings, factory
    ):
        user = await factory.user()
        await AgreementService(session).accept(user.id, GUILD_ID, 1)
        await GuildRepository(session).update_settings(GUILD_ID, rules_version=2)

        decision = await AccessService(session, settings).check(
            internal_user_id=user.id, guild_id=GUILD_ID, require_agreement=True
        )
        assert decision.needs_agreement
        assert decision.is_reacceptance
