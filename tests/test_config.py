"""Tests for configuration module."""

import pytest

from hvcwatch.config import Settings


@pytest.fixture
def base_env() -> dict[str, str]:
    """🧰 Environment with the required Fastmail vars and one Discord URL."""
    return {
        "FASTMAIL_USER": "test@example.com",
        "FASTMAIL_PASS": "password123",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
    }


class TestSettingsBasic:
    """Test basic Settings functionality."""

    def test_settings_with_all_required_fields(self):
        """✅ Test Settings with all required fields provided."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            massive_api_key="test-api-key",
        )

        assert settings.fastmail_user == "test@example.com"
        assert settings.fastmail_pass == "password123"
        assert settings.discord_webhook_url == "https://discord.com/api/webhooks/test"
        assert settings.massive_api_key == "test-api-key"


class TestSettingsMassiveApiKey:
    """Test loading the Massive API key from the environment."""

    def test_massive_api_key_env_var_populates_massive_api_key(self, base_env):
        """🔑 MASSIVE_API_KEY populates massive_api_key."""
        # Arrange
        env = {**base_env, "MASSIVE_API_KEY": "massive-key"}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert settings.massive_api_key == "massive-key"


class TestSettingsDefaults:
    """Test Settings default values."""

    def test_default_log_level(self):
        """✅ Test default log level is INFO."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            massive_api_key="test-api-key",
        )

        assert settings.log_level == "INFO"

    def test_default_imap_settings(self):
        """✅ Test default IMAP settings."""
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url="https://discord.com/api/webhooks/test",
            massive_api_key="test-api-key",
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
            massive_api_key="test-api-key",
        )

        assert settings.transparent_png == "https://major.io/transparent.png"


class TestSettingsValidation:
    """Test Settings validation rules."""

    def test_no_discord_urls_raises_value_error(self):
        """🚫 Settings without any Discord webhook URL is rejected."""
        with pytest.raises(ValueError, match="Discord webhook URL"):
            Settings(fastmail_user="test@example.com", fastmail_pass="password123")


class TestSettingsFromEnv:
    """Test loading Settings from environment variables."""

    def test_required_vars_only_uses_defaults(self, base_env):
        """✅ Only the required vars and one Discord URL leave defaults in place."""
        # Act
        settings = Settings.from_env(env=base_env)

        # Assert
        assert settings.imap_port == 993
        assert settings.hvc_weekly_enabled is True
        assert settings.hvc_daily_enabled is False

    def test_int_vars_are_coerced(self, base_env):
        """🔢 IMAP_PORT becomes an int."""
        # Arrange
        env = {**base_env, "IMAP_PORT": "1143"}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert settings.imap_port == 1143

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("On", True),
            ("0", False),
            ("false", False),
            ("No", False),
            ("OFF", False),
        ],
    )
    def test_bool_spellings_are_parsed(self, base_env, raw, expected):
        """🔘 Common truthy and falsy spellings are accepted, case-insensitively."""
        # Arrange
        env = {**base_env, "HVC_DAILY_ENABLED": raw}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert settings.hvc_daily_enabled is expected

    @pytest.mark.parametrize(
        ("name", "raw"),
        [
            ("HVC_DAILY_ENABLED", "maybe"),
            ("IMAP_PORT", "abc"),
        ],
    )
    def test_invalid_value_error_names_variable(self, base_env, name, raw):
        """❌ A value that does not match its type raises ValueError naming the var."""
        # Arrange
        env = {**base_env, name: raw}

        # Act / Assert
        with pytest.raises(ValueError, match=name):
            Settings.from_env(env=env)

    def test_missing_required_vars_are_all_listed(self):
        """❌ Missing FASTMAIL_USER and FASTMAIL_PASS are both named in the error."""
        # Arrange
        env = {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"}

        # Act
        with pytest.raises(ValueError) as excinfo:
            Settings.from_env(env=env)

        # Assert
        assert "FASTMAIL_USER" in str(excinfo.value)
        assert "FASTMAIL_PASS" in str(excinfo.value)


class TestGetDiscordWebhookUrls:
    """Test merging of Discord webhook URL settings."""

    def test_merges_strips_dedupes_and_preserves_order(self):
        """📋 Legacy and comma-separated URLs merge in order with no duplicates."""
        # Arrange
        settings = Settings(
            fastmail_user="test@example.com",
            fastmail_pass="password123",
            discord_webhook_url=" https://discord.com/api/webhooks/a ",
            discord_webhook_urls=(
                " https://discord.com/api/webhooks/b, "
                "https://discord.com/api/webhooks/a ,, "
                "https://discord.com/api/webhooks/c "
            ),
        )

        # Act
        urls = settings.get_discord_webhook_urls()

        # Assert
        assert urls == [
            "https://discord.com/api/webhooks/a",
            "https://discord.com/api/webhooks/b",
            "https://discord.com/api/webhooks/c",
        ]
