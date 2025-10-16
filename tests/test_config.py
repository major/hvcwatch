"""Tests for configuration module."""

import pytest

from hvcwatch.config import Settings


class TestSettingsBasic:
    """Test basic Settings functionality."""

    def test_settings_with_all_required_fields(self):
        """✅ Test Settings with all required fields provided."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
        )

        assert settings.fastmail_user == "test@example.com"
        assert settings.fastmail_pass == "password123"
        assert settings.discord_webhook_url == "https://discord.com/api/webhooks/test"
        assert settings.polygon_api_key == "test-api-key"
        # Mastodon fields should be None by default
        assert settings.mastodon_server_url is None
        assert settings.mastodon_access_token is None

    def test_settings_with_optional_mastodon_fields(self):
        """✅ Test Settings with optional Mastodon fields provided."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social",
            mastodon_access_token="mastodon-token-123",
        )

        assert settings.mastodon_server_url == "https://mastodon.social"
        assert settings.mastodon_access_token == "mastodon-token-123"

    def test_settings_with_all_required_and_mastodon(self):
        """✅ Test Settings with both Discord and Mastodon configured."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social",
            mastodon_access_token="mastodon-token",
        )

        assert settings.discord_webhook_url is not None
        assert settings.mastodon_server_url == "https://mastodon.social"
        assert settings.mastodon_access_token == "mastodon-token"


class TestSettingsDefaults:
    """Test Settings default values."""

    def test_default_log_level(self):
        """✅ Test default log level is INFO."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
        )

        assert settings.log_level == "INFO"

    def test_default_imap_settings(self):
        """✅ Test default IMAP settings."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
        )

        assert settings.imap_host == "imap.fastmail.com"
        assert settings.imap_port == 993
        assert settings.imap_folder == "Trading/ToS Alerts"

    def test_default_transparent_png(self):
        """✅ Test default transparent PNG URL."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
        )

        assert settings.transparent_png == "https://major.io/transparent.png"


class TestSettingsPlatformConfiguration:
    """Test platform-specific configuration scenarios."""

    def test_discord_only_configuration(self):
        """✅ Test configuration with Discord only (no Mastodon)."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            # Mastodon fields explicitly None
            mastodon_server_url=None,
            mastodon_access_token=None,
        )

        # Discord configured
        assert settings.discord_webhook_url is not None
        # Mastodon not configured
        assert settings.mastodon_server_url is None
        assert settings.mastodon_access_token is None

    def test_mastodon_only_configuration(self):
        """✅ Test configuration with Mastodon only (Discord still required by schema)."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",  # Still required
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social",
            mastodon_access_token="mastodon-token",
        )

        assert settings.mastodon_server_url == "https://mastodon.social"
        assert settings.mastodon_access_token == "mastodon-token"

    def test_both_platforms_configured(self):
        """✅ Test configuration with both Discord and Mastodon."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social",
            mastodon_access_token="mastodon-token",
        )

        # Both platforms configured
        assert settings.discord_webhook_url is not None
        assert settings.mastodon_server_url is not None
        assert settings.mastodon_access_token is not None

    def test_partial_mastodon_configuration_server_only(self):
        """⚠️ Test partial Mastodon configuration (server URL only)."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social",
            # mastodon_access_token not provided
        )

        assert settings.mastodon_server_url == "https://mastodon.social"
        assert settings.mastodon_access_token is None

    def test_partial_mastodon_configuration_token_only(self):
        """⚠️ Test partial Mastodon configuration (access token only)."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            # mastodon_server_url not provided
            mastodon_access_token="mastodon-token",
        )

        assert settings.mastodon_server_url is None
        assert settings.mastodon_access_token == "mastodon-token"


class TestSettingsMastodonServers:
    """Test Mastodon configuration with different server URLs."""

    @pytest.mark.parametrize(
        "server_url",
        [
            "https://mastodon.social",
            "https://fosstodon.org",
            "https://mas.to",
            "https://mastodon.online",
            "https://techhub.social",
        ],
    )
    def test_various_mastodon_servers(self, server_url):
        """✅ Test configuration with various Mastodon server URLs."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url=server_url,
            mastodon_access_token="token",
        )

        assert settings.mastodon_server_url == server_url

    def test_mastodon_server_with_trailing_slash(self):
        """✅ Test Mastodon server URL with trailing slash (should work)."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
            mastodon_server_url="https://mastodon.social/",
            mastodon_access_token="token",
        )

        # Pydantic accepts the trailing slash as-is
        assert settings.mastodon_server_url == "https://mastodon.social/"
