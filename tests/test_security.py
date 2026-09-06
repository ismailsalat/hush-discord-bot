"""Privacy primitives. These are the guarantees everything else rests on."""

from __future__ import annotations

import pytest

from app.security.identifiers import (
    build_custom_id,
    format_alias,
    new_confession_id,
    new_error_id,
    new_internal_user_id,
    normalize_alias,
)
from app.security.privacy import anonymity_notice, scrub


class TestCustomIdTripwire:
    """A Discord id or internal user id must never reach a button custom id."""

    def test_confession_id_is_allowed(self):
        assert build_custom_id("rate", "conf_abc123") == "cf:rate:conf_abc123"

    def test_internal_user_id_is_rejected(self):
        with pytest.raises(ValueError):
            build_custom_id("rate", new_internal_user_id())

    @pytest.mark.parametrize("snowflake", ["123456789012345678", "98765432109876543"])
    def test_discord_snowflake_is_rejected(self, snowflake):
        with pytest.raises(ValueError):
            build_custom_id("rate", snowflake)

    def test_embedded_snowflake_is_rejected(self):
        with pytest.raises(ValueError):
            build_custom_id("rate", "conf_x:123456789012345678")


class TestIdentifiers:
    def test_ids_have_stable_prefixes(self):
        assert new_internal_user_id().startswith("usr_")
        assert new_confession_id().startswith("conf_")

    def test_error_ids_are_short_and_shoutable(self):
        error_id = new_error_id()
        assert error_id.startswith("ERR-")
        assert len(error_id) <= 10

    def test_ids_are_unique(self):
        assert len({new_confession_id() for _ in range(500)}) == 500

    def test_alias_formatting(self):
        assert format_alias("A17") == "Anon #A17"

    @pytest.mark.parametrize("raw", ["A17", "a17", "#A17", "Anon #A17", " anon #a17 "])
    def test_alias_normalisation_accepts_what_people_type(self, raw):
        assert normalize_alias(raw) == "A17"

    def test_nonsense_alias_is_rejected(self):
        assert normalize_alias("not an alias!!") is None


class TestPrivacyHelpers:
    def test_secrets_are_scrubbed(self):
        cleaned = scrub({"discord_token": "hunter2", "nested": {"password": "x"}, "ok": 1})
        assert cleaned["discord_token"] != "hunter2"
        assert cleaned["nested"]["password"] != "x"
        assert cleaned["ok"] == 1

    def test_anonymity_notice_is_honest(self):
        notice = anonymity_notice("Hush").lower()
        # It must never promise total anonymity.
        assert "completely anonymous" not in notice
        assert "retains" in notice or "moderation" in notice
