"""Configuration values for the stocknews package."""

import os
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from functools import cache
from typing import Any

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _parse_bool(name: str, raw: str) -> bool:
    """
    🔘 Parse a boolean env value.

    Args:
        name: Env var name, used in the error message.
        raw: Raw string value from the environment.

    Returns:
        True or False for the accepted spellings (case-insensitive).

    Raises:
        ValueError: If the value is not an accepted boolean spelling.
    """
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    msg = f"{name} must be one of 1/true/yes/on or 0/false/no/off, got {raw!r}"
    raise ValueError(msg)


def _parse_int(name: str, raw: str) -> int:
    """
    🔢 Convert an int env value, naming the variable on failure.

    Args:
        name: Env var name, used in the error message.
        raw: Raw string value from the environment.

    Returns:
        The value as an int.

    Raises:
        ValueError: If the value is not a valid int.
    """
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"{name} must be a valid int, got {raw!r}"
        raise ValueError(msg) from exc


def _coerce(name: str, raw: str, target: Any) -> Any:
    """
    🔄 Convert a raw env string to the type of a Settings field.

    Args:
        name: Env var name, used in error messages.
        raw: Raw string value from the environment.
        target: The field type with `str | None` already reduced to `str`.

    Returns:
        The value in the target type. Strings are returned unchanged.
    """
    if target is bool:
        return _parse_bool(name, raw)
    if target is int:
        return _parse_int(name, raw)
    return raw


def _base_type(annotation: Any) -> Any:
    """
    🧭 Reduce `str | None` to `str` so coercion only sees the core type.

    Args:
        annotation: The field's type annotation.

    Returns:
        `str` for `str | None`, otherwise the annotation unchanged.
    """
    return str if annotation == str | None else annotation


@dataclass(frozen=True)
class Settings:
    """⚙️ Runtime configuration, usually built with Settings.from_env()."""

    # Fastmail credentials (required)
    fastmail_user: str
    fastmail_pass: str

    # Discord configuration - supports multiple webhooks
    discord_webhook_url: str | None = None  # Deprecated, use discord_webhook_urls
    discord_webhook_urls: str | None = None  # Comma-separated Discord webhook URLs

    massive_api_key: str | None = None  # Massive API key for company name and ticker type lookups

    hvcwatch_db_path: str | None = None  # SQLite database path for alert tracking

    log_level: str = "INFO"

    # HVC alert type toggles
    hvc_daily_enabled: bool = False
    hvc_weekly_enabled: bool = True
    hvc_monthly_enabled: bool = True

    imap_host: str = "imap.fastmail.com"
    imap_port: int = 993
    imap_folder: str = "Trading/ToS Alerts"  # IMAP folder to monitor

    transparent_png: str = "https://major.io/transparent.png"

    def __post_init__(self) -> None:
        """
        🔍 Validate Discord webhook configuration.

        Ensures at least one usable Discord webhook URL is provided (either via
        discord_webhook_url or discord_webhook_urls). Whitespace-only and empty
        entries do not count. This maintains backward compatibility while
        supporting the new multi-webhook feature.

        Raises:
            ValueError: If no usable Discord webhook URLs are configured
        """
        # 🧹 Use the same cleanup as get_discord_webhook_urls()
        if not self._clean_discord_urls():
            msg = (
                "At least one Discord webhook URL must be provided via "
                "DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URLS"
            )
            raise ValueError(msg)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """
        🌱 Build Settings from environment variables.

        Each field reads the env var with its UPPERCASE name. Fields with no env
        var set use their dataclass default. Values are coerced to the field type.
        Only env vars are read, not .env files.

        Args:
            env: Mapping to read from. Defaults to os.environ.

        Returns:
            A validated Settings instance.

        Raises:
            ValueError: If a required var is missing, a value cannot be parsed,
                or no Discord webhook URL is configured. The missing-vars error
                lists every missing name.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        missing: list[str] = []

        for f in fields(cls):
            name = f.name.upper()
            if name in source:
                kwargs[f.name] = _coerce(name, source[name], _base_type(f.type))
            elif f.default is MISSING and f.default_factory is MISSING:
                missing.append(name)

        if missing:
            msg = f"Missing required environment variables: {', '.join(missing)}"
            raise ValueError(msg)
        return cls(**kwargs)

    def _clean_discord_urls(self) -> list[str]:
        """
        🧹 Collect usable Discord webhook URLs from both settings.

        Strips whitespace, drops empty entries, and removes duplicates while
        keeping order. The legacy single URL comes first, then the
        comma-separated URLs. The single URL is not split on commas.

        Returns:
            Cleaned, unique URLs. Empty when no usable URL is configured.
        """
        candidates: list[str] = []
        if self.discord_webhook_url:
            candidates.append(self.discord_webhook_url)
        if self.discord_webhook_urls:
            candidates.extend(self.discord_webhook_urls.split(","))

        stripped = (url.strip() for url in candidates)
        # 🔁 dict keys keep insertion order and drop duplicates
        return list(dict.fromkeys(url for url in stripped if url))

    def get_discord_webhook_urls(self) -> list[str]:
        """
        📋 Get list of Discord webhook URLs from configuration.

        Combines both the legacy single URL (discord_webhook_url) and the new
        comma-separated URLs (discord_webhook_urls) into a single list.

        Returns:
            List of Discord webhook URLs (deduplicated and stripped)

        Example:
            >>> settings = Settings(
            ...     fastmail_user="u",
            ...     fastmail_pass="p",
            ...     discord_webhook_url="https://discord.com/api/webhooks/1",
            ...     discord_webhook_urls="https://discord.com/api/webhooks/2,https://discord.com/api/webhooks/3",
            ... )
            >>> settings.get_discord_webhook_urls()
            ['https://discord.com/api/webhooks/1', 'https://discord.com/api/webhooks/2', 'https://discord.com/api/webhooks/3']
        """
        return self._clean_discord_urls()


@cache
def get_settings() -> Settings:
    """
    ⚙️ Return the app Settings, read from os.environ on the first call.

    The read is lazy, so importing this module never fails when env vars are
    missing. A missing required var raises ValueError on the first call. Errors
    are not cached, so a later call tries again.

    Returns:
        The shared Settings instance for this process.
    """
    return Settings.from_env()
