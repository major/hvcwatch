"""Configuration values for the stocknews package."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    fastmail_user: str = Field(..., description="Fastmail username")
    fastmail_pass: str = Field(..., description="Fastmail password")

    discord_webhook_url: str = Field(..., description="Discord webhook URL")

    mastodon_server_url: str | None = Field(
        None, description="Mastodon server URL (e.g., 'https://mastodon.social')"
    )
    mastodon_access_token: str | None = Field(
        None, description="Mastodon user access token for posting statuses"
    )

    polygon_api_key: str = Field(..., description="Polygon.io API key")

    log_level: str = Field("INFO", description="Log level")

    imap_host: str = Field("imap.fastmail.com", description="IMAP server host")
    imap_port: int = Field(993, description="IMAP server port")

    imap_folder: str = Field("Trading/ToS Alerts", description="IMAP folder to monitor")

    transparent_png: str = "https://major.io/transparent.png"


settings = Settings()  # type: ignore[call-arg]
