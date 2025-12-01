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


class TestSettingsDiscordConfiguration:
    """Test Discord-specific configuration scenarios."""

    def test_discord_configuration(self):
        """✅ Test configuration with Discord webhook URL."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            polygon_api_key="test-api-key",
        )

        assert settings.discord_webhook_url is not None
