"""Tests for configuration module.

Every case goes through Settings.from_env with an explicit mapping, so the
tests never read the real environment.
"""

import pytest

from hvcwatch.config import Settings

URL_A = "https://discord.com/api/webhooks/a"
URL_B = "https://discord.com/api/webhooks/b"
URL_C = "https://discord.com/api/webhooks/c"


@pytest.fixture
def base_env() -> dict[str, str]:
    """🧰 Environment with the required Fastmail vars and one Discord URL."""
    return {
        "FASTMAIL_USER": "test@example.com",
        "FASTMAIL_PASS": "password123",
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
    }


class TestFromEnvDefaults:
    """Fields with no env var keep their dataclass defaults."""

    def test_required_vars_only_uses_defaults(self, base_env):
        """✅ Only the required vars and one Discord URL leave every default in place."""
        # Act
        settings = Settings.from_env(env=base_env)

        # Assert
        assert settings.fastmail_user == "test@example.com"
        assert settings.fastmail_pass == "password123"
        assert settings.discord_webhook_url == "https://discord.com/api/webhooks/test"
        assert settings.discord_webhook_urls is None
        assert settings.massive_api_key is None
        assert settings.hvcwatch_db_path is None
        assert settings.log_level == "INFO"
        assert settings.hvc_daily_enabled is False
        assert settings.hvc_weekly_enabled is True
        assert settings.hvc_monthly_enabled is True
        assert settings.imap_host == "imap.fastmail.com"
        assert settings.imap_port == 993
        assert settings.imap_folder == "Trading/ToS Alerts"
        assert settings.transparent_png == "https://major.io/transparent.png"


class TestFromEnvValues:
    """Env vars populate the matching field, coerced to its type."""

    @pytest.mark.parametrize(
        ("name", "raw", "field", "expected"),
        [
            ("MASSIVE_API_KEY", "massive-key", "massive_api_key", "massive-key"),
            ("MASSIVE_API_KEY", "", "massive_api_key", ""),
            (
                "DISCORD_WEBHOOK_URLS",
                f"{URL_A},{URL_B}",
                "discord_webhook_urls",
                f"{URL_A},{URL_B}",
            ),
            (
                "HVCWATCH_DB_PATH",
                "/tmp/alerts.db",
                "hvcwatch_db_path",
                "/tmp/alerts.db",
            ),
            ("LOG_LEVEL", "DEBUG", "log_level", "DEBUG"),
            ("IMAP_HOST", "imap.example.com", "imap_host", "imap.example.com"),
            ("IMAP_PORT", "1143", "imap_port", 1143),
            ("IMAP_FOLDER", "INBOX", "imap_folder", "INBOX"),
            (
                "TRANSPARENT_PNG",
                "https://example.com/t.png",
                "transparent_png",
                "https://example.com/t.png",
            ),
        ],
    )
    def test_env_var_populates_field(self, base_env, name, raw, field, expected):
        """🔑 Each env var lands in its own field with the right type."""
        # Arrange
        env = {**base_env, name: raw}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert getattr(settings, field) == expected

    def test_legacy_polygon_api_key_is_ignored(self, base_env):
        """🪦 POLYGON_API_KEY no longer fills massive_api_key."""
        # Arrange
        env = {**base_env, "POLYGON_API_KEY": "old-key"}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert settings.massive_api_key is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("On", True),
            (" true ", True),
            ("0", False),
            ("false", False),
            ("No", False),
            ("OFF", False),
            ("\toff\n", False),
        ],
    )
    def test_bool_spellings_are_parsed(self, base_env, raw, expected):
        """🔘 Truthy and falsy spellings are accepted, ignoring case and whitespace."""
        # Arrange
        env = {**base_env, "HVC_DAILY_ENABLED": raw}

        # Act
        settings = Settings.from_env(env=env)

        # Assert
        assert settings.hvc_daily_enabled is expected


class TestFromEnvErrors:
    """Bad input raises ValueError with a message that names the problem."""

    @pytest.mark.parametrize(
        ("name", "raw"),
        [
            ("HVC_DAILY_ENABLED", "maybe"),
            ("HVC_DAILY_ENABLED", ""),
            ("HVC_WEEKLY_ENABLED", "   "),
            ("IMAP_PORT", "abc"),
            ("IMAP_PORT", ""),
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

    @pytest.mark.parametrize(
        "discord_env",
        [
            pytest.param({}, id="no-discord-vars"),
            pytest.param({"DISCORD_WEBHOOK_URL": ""}, id="empty-url"),
            pytest.param({"DISCORD_WEBHOOK_URLS": ""}, id="empty-urls"),
            pytest.param({"DISCORD_WEBHOOK_URL": "   "}, id="blank-url"),
            pytest.param({"DISCORD_WEBHOOK_URLS": ","}, id="comma-only-urls"),
            pytest.param({"DISCORD_WEBHOOK_URLS": " , "}, id="spaced-comma-urls"),
            pytest.param(
                {"DISCORD_WEBHOOK_URL": "  ", "DISCORD_WEBHOOK_URLS": ","},
                id="blank-url-and-comma-urls",
            ),
        ],
    )
    def test_no_discord_url_is_rejected(self, discord_env):
        """🚫 A config with no Discord webhook URL fails and names the variable."""
        # Arrange
        env = {"FASTMAIL_USER": "u", "FASTMAIL_PASS": "p", **discord_env}

        # Act / Assert
        with pytest.raises(ValueError, match="DISCORD_WEBHOOK_URL"):
            Settings.from_env(env=env)


class TestGetDiscordWebhookUrls:
    """Test merging of Discord webhook URL settings."""

    def test_merges_strips_dedupes_and_preserves_order(self):
        """📋 Legacy and comma-separated URLs merge in order with no duplicates."""
        # Arrange
        env = {
            "FASTMAIL_USER": "test@example.com",
            "FASTMAIL_PASS": "password123",
            "DISCORD_WEBHOOK_URL": f" {URL_A} ",
            "DISCORD_WEBHOOK_URLS": f" {URL_B}, {URL_A} ,, {URL_C} ",
        }

        # Act
        urls = Settings.from_env(env=env).get_discord_webhook_urls()

        # Assert
        assert urls == [URL_A, URL_B, URL_C]

    def test_urls_var_alone_is_enough(self):
        """📋 DISCORD_WEBHOOK_URLS works without DISCORD_WEBHOOK_URL."""
        # Arrange
        env = {
            "FASTMAIL_USER": "test@example.com",
            "FASTMAIL_PASS": "password123",
            "DISCORD_WEBHOOK_URLS": f"{URL_A},{URL_B}",
        }

        # Act
        urls = Settings.from_env(env=env).get_discord_webhook_urls()

        # Assert
        assert urls == [URL_A, URL_B]
