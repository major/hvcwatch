"""Configuration values for the stocknews package."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    fastmail_user: str = Field(..., description="Fastmail username")
    fastmail_pass: str = Field(..., description="Fastmail password")

    # Discord configuration - supports multiple webhooks
    discord_webhook_url: str | None = Field(
        None, description="Discord webhook URL (deprecated, use discord_webhook_urls)"
    )
    discord_webhook_urls: str | None = Field(
        None, description="Comma-separated Discord webhook URLs"
    )

    polygon_api_key: str | None = Field(
        None, description="Polygon.io API key (no longer used)"
    )

    hvcwatch_db_path: str | None = Field(
        None, description="Path to SQLite database for alert tracking"
    )

    sentry_dsn: str | None = Field(
        None, description="Sentry DSN for error tracking (optional)"
    )
    sentry_environment: str = Field("production", description="Sentry environment name")
    sentry_traces_sample_rate: float = Field(
        1.0, description="Sentry traces sample rate (0.0 to 1.0)"
    )

    log_level: str = Field("INFO", description="Log level")

    # HVC alert type toggles
    hvc_daily_enabled: bool = Field(False, description="Enable daily HVC alerts")
    hvc_weekly_enabled: bool = Field(True, description="Enable weekly HVC alerts")
    hvc_monthly_enabled: bool = Field(True, description="Enable monthly HVC alerts")

    imap_host: str = Field("imap.fastmail.com", description="IMAP server host")
    imap_port: int = Field(993, description="IMAP server port")

    imap_folder: str = Field("Trading/ToS Alerts", description="IMAP folder to monitor")

    transparent_png: str = "https://major.io/transparent.png"

    @model_validator(mode="after")
    def validate_discord_config(self) -> "Settings":
        """
        🔍 Validate Discord webhook configuration.

        Ensures at least one Discord webhook URL is provided (either via
        discord_webhook_url or discord_webhook_urls). This maintains backward
        compatibility while supporting the new multi-webhook feature.

        Returns:
            Self with validated Discord configuration

        Raises:
            ValueError: If no Discord webhook URLs are configured
        """
        if not self.discord_webhook_url and not self.discord_webhook_urls:
            msg = (
                "At least one Discord webhook URL must be provided via "
                "DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URLS"
            )
            raise ValueError(msg)
        return self

    def get_discord_webhook_urls(self) -> list[str]:
        """
        📋 Get list of Discord webhook URLs from configuration.

        Combines both the legacy single URL (discord_webhook_url) and the new
        comma-separated URLs (discord_webhook_urls) into a single list.

        Returns:
            List of Discord webhook URLs (deduplicated and stripped)

        Example:
            >>> settings.discord_webhook_url = "https://discord.com/api/webhooks/1"
            >>> settings.discord_webhook_urls = "https://discord.com/api/webhooks/2,https://discord.com/api/webhooks/3"
            >>> settings.get_discord_webhook_urls()
            ['https://discord.com/api/webhooks/1', 'https://discord.com/api/webhooks/2', 'https://discord.com/api/webhooks/3']
        """
        urls: list[str] = []

        # Add legacy single URL if present
        if self.discord_webhook_url:
            urls.append(self.discord_webhook_url.strip())

        # Add comma-separated URLs if present
        if self.discord_webhook_urls:
            # Split by comma and strip whitespace
            new_urls = [url.strip() for url in self.discord_webhook_urls.split(",")]
            # Filter out empty strings
            new_urls = [url for url in new_urls if url]
            urls.extend(new_urls)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduplicated: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduplicated.append(url)

        return deduplicated


settings = Settings()  # type: ignore[call-arg]
