"""Embeds and persistent components.

The presentation layer is where a privacy mistake would be most visible, so
these tests assert on what is *absent* as much as what is present.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from app.config.settings import Settings
from app.embeds.agreement import PROHIBITED_RULES, AgreementEmbedBuilder
from app.embeds.confession import ConfessionEmbedBuilder
from app.embeds.errors import ErrorEmbedBuilder
from app.embeds.factory import Colors, EmbedFactory
from app.embeds.moderation import ModerationEmbedBuilder
from app.embeds.profile import ProfileEmbedBuilder
from app.services.dto import ConfessionStats, ConfessionView, ProfileView

DISCORD_ID = "123456789012345678"
INTERNAL_ID = "usr_deadbeefdeadbeef"


@pytest.fixture
def factory_embeds():
    return EmbedFactory(Settings())


@pytest.fixture
def view():
    return ConfessionView(
        confession_id="conf_abc123",
        guild_id=1,
        public_number=184,
        alias_display="Anon #A17",
        alias_id="ali_1",
        content="I still have not told anyone about this.",
        created_at=datetime(2026, 7, 20, 17, 42, tzinfo=UTC),
        stats=ConfessionStats(
            average_rating=4.3, rating_count=87, bookmark_count=12, reply_count=24
        ),
    )


class TestConfessionEmbed:
    def test_layout_matches_the_design(self, factory_embeds, view):
        embed = ConfessionEmbedBuilder(factory_embeds).build(view)
        assert embed.title == "Anon #A17 — Confession #184"
        assert embed.color.value == Colors.BRAND
        assert "4.3 / 5" in embed.description
        assert "87 ratings" in embed.description
        assert "24 replies" in embed.description
        assert "12 bookmarks" in embed.description

    def test_footer_states_the_honest_anonymity_claim(self, factory_embeds, view):
        embed = ConfessionEmbedBuilder(factory_embeds).build(view)
        assert embed.footer.text == "Anonymous to regular server members."

    def test_no_identity_appears_anywhere(self, factory_embeds, view):
        embed = ConfessionEmbedBuilder(factory_embeds).build(view)
        rendered = str(embed.to_dict())
        assert DISCORD_ID not in rendered
        assert "usr_" not in rendered

    def test_unrated_confession_reads_naturally(self, factory_embeds, view):
        bare = dataclasses.replace(
            view,
            stats=ConfessionStats(
                average_rating=None, rating_count=0, bookmark_count=0, reply_count=0
            ),
        )
        embed = ConfessionEmbedBuilder(factory_embeds).build(bare)
        assert "not yet rated" in embed.description

    def test_update_links_to_its_original(self, factory_embeds, view):
        update = dataclasses.replace(
            view, parent_confession_id="conf_parent", parent_number=100
        )
        embed = ConfessionEmbedBuilder(factory_embeds).build(update)
        assert any("Confession #100" in field.name for field in embed.fields)

    def test_mentions_are_neutralised(self, factory_embeds, view):
        loud = dataclasses.replace(view, content="hey @everyone and <@1234>")
        embed = ConfessionEmbedBuilder(factory_embeds).build(loud)
        assert "@everyone" not in embed.description

    def test_preview_shows_the_character_count(self, factory_embeds):
        embed = ConfessionEmbedBuilder(factory_embeds).preview("hello", 1500)
        assert any("1,500" in field.value for field in embed.fields)


class TestProfileEmbed:
    def test_profile_shows_only_alias_level_data(self, factory_embeds):
        profile = ProfileView(
            alias_id="ali_1",
            alias_display="Anon #A17",
            guild_id=1,
            is_current=True,
            confession_count=14,
            average_rating=4.3,
            rating_count=87,
            follower_count=38,
            most_rated_number=None,
            most_rated_rating_count=0,
        )
        embed = ProfileEmbedBuilder(factory_embeds).build(profile)
        rendered = str(embed.to_dict())
        assert embed.title == "Anon #A17"
        assert DISCORD_ID not in rendered
        assert INTERNAL_ID not in rendered

    def test_retired_identity_is_labelled(self, factory_embeds):
        profile = ProfileView(
            alias_id="ali_1",
            alias_display="Anon #A17",
            guild_id=1,
            is_current=False,
            confession_count=1,
            average_rating=None,
            rating_count=0,
            follower_count=0,
            most_rated_number=None,
            most_rated_rating_count=0,
        )
        embed = ProfileEmbedBuilder(factory_embeds).build(profile)
        assert any("retired" in field.value.lower() for field in embed.fields)


class TestAgreementEmbed:
    def test_every_prohibited_category_is_listed(self, factory_embeds):
        embed = AgreementEmbedBuilder(factory_embeds).rules(version=1)
        for rule in PROHIBITED_RULES:
            assert rule in embed.description

    def test_edgy_content_is_explicitly_allowed(self, factory_embeds):
        embed = AgreementEmbedBuilder(factory_embeds).rules(version=1)
        assert "Dark humour" in embed.description

    def test_version_is_shown(self, factory_embeds):
        embed = AgreementEmbedBuilder(factory_embeds).rules(version=7)
        assert "version 7" in embed.footer.text

    def test_reacceptance_has_different_wording(self, factory_embeds):
        first = AgreementEmbedBuilder(factory_embeds).rules(version=1)
        again = AgreementEmbedBuilder(factory_embeds).rules(version=2, is_reacceptance=True)
        assert first.title != again.title

    def test_rotation_warning_explains_the_tradeoff(self, factory_embeds):
        embed = AgreementEmbedBuilder(factory_embeds).alias_rotation_notice(
            current_alias="Anon #A17", available_on=None, can_rotate=True
        )
        assert "followers" in embed.description.lower()


class TestModerationEmbeds:
    def test_ban_notice_separates_hush_from_discord(self, factory_embeds):
        embed = ModerationEmbedBuilder(factory_embeds).ban_notice(
            duration="7 days", reason="harassment", guild_name="Test"
        )
        rendered = str(embed.to_dict())
        assert "does not affect your Discord membership" in rendered

    def test_mod_log_shows_alias_not_identity(self, factory_embeds):
        embed = ModerationEmbedBuilder(factory_embeds).mod_log(
            action="Warning Issued",
            alias_display="Anon #A17",
            moderator="<@42>",
            reason="rule break",
            confession_number=184,
        )
        rendered = str(embed.to_dict())
        assert "Anon #A17" in rendered
        assert DISCORD_ID not in rendered


class TestErrorEmbeds:
    def test_error_id_is_surfaced(self, factory_embeds):
        embed = ErrorEmbedBuilder(factory_embeds).posting_failed(error_id="ERR-X7B29")
        assert any("ERR-X7B29" in field.value for field in embed.fields)

    def test_failed_post_reassures_about_the_draft(self, factory_embeds):
        embed = ErrorEmbedBuilder(factory_embeds).posting_failed(error_id="ERR-1")
        assert "draft was saved" in embed.description

    def test_known_errors_use_their_own_wording(self, factory_embeds):
        from app.core.exceptions import AgreementRequiredError

        embed = ErrorEmbedBuilder(factory_embeds).from_exception(AgreementRequiredError())
        assert embed.color.value in (Colors.WARNING, Colors.ERROR)
        assert embed.description


class TestPersistentComponents:
    def test_confession_row_has_exactly_four_buttons(self):
        from app.views.confession import ConfessionActionView

        buttons = ConfessionActionView("conf_abc123").children
        assert [button.item.label for button in buttons] == [
            "Rate",
            "Profile",
            "Follow",
            "More",
        ]
        # A plain ellipsis is text, not a Discord emoji. The old code
        # sent it as an emoji and Discord rejected the entire confession post.
        assert buttons[-1].item.emoji is None

    def test_custom_ids_round_trip(self):
        """A restart must be able to rebuild the button from its custom id alone."""
        from app.views.confession import RateConfessionButton

        button = RateConfessionButton("conf_abc123")
        custom_id = button.item.custom_id
        match = RateConfessionButton.__discord_ui_compiled_template__.fullmatch(custom_id)
        assert match is not None
        assert match["cid"] == "conf_abc123"

    def test_poll_buttons_encode_their_option(self):
        from app.views.polls import PollVoteButton, PollView

        view = PollView("pol_abc123", ["Yes", "No", "Maybe"])
        ids = [child.item.custom_id for child in view.children]
        assert ids == ["cf:pv:pol_abc123:0", "cf:pv:pol_abc123:1", "cf:pv:pol_abc123:2"]

        match = PollVoteButton.__discord_ui_compiled_template__.fullmatch(ids[2])
        assert match["pid"] == "pol_abc123" and match["idx"] == "2"

    def test_follow_button_is_hidden_when_disabled(self):
        from app.views.confession import ConfessionActionView

        class Settings:
            followers_enabled = False

        labels = [c.item.label for c in ConfessionActionView("conf_abc123", settings=Settings()).children]
        assert "Follow" not in labels

    def test_no_custom_id_contains_an_identity(self):
        from app.views.confession import ConfessionActionView

        for child in ConfessionActionView("conf_abc123").children:
            assert "usr_" not in child.item.custom_id
            assert DISCORD_ID not in child.item.custom_id
