# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**hvcwatch** is a bot that monitors email inbox for trading alerts from ThinkOrSwim and forwards them to Discord and Mastodon with enriched market data.

## Core Architecture

### Data Flow
1. **Email Monitor** ([email_monitor.py](src/hvcwatch/email_monitor.py)) connects to IMAP (Fastmail) and monitors "Trading/ToS Alerts" folder using IDLE protocol
2. **Email Processing** extracts ticker symbols from email subjects using regex patterns
3. **Market Hours Filter** ([utils.py](src/hvcwatch/utils.py)) validates that alerts arrive during/near market hours using NYSE calendar
4. **Data Enrichment** fetches ticker data from Polygon.io API:
   - Company details and logo
   - Current price and volume
   - 20-day volume moving average
   - Creates `TickerData` model with enriched data
5. **Multi-Platform Notification** ([notification.py](src/hvcwatch/notification.py)) orchestrates notifications:
   - `notify_all_platforms()` fetches data once and sends to all enabled platforms
   - Discord notifier sends rich embeds with company logos
   - Mastodon notifier sends text statuses with emojis and hashtags
   - Graceful degradation: platforms fail independently

### Key Components

- **[config.py](src/hvcwatch/config.py)**: Pydantic Settings for environment variables (`.env` file)
  - Required: `FASTMAIL_USER`, `FASTMAIL_PASS`, `DISCORD_WEBHOOK_URL`, `POLYGON_API_KEY`
  - Optional: `MASTODON_SERVER_URL`, `MASTODON_ACCESS_TOKEN` (both required to enable Mastodon)
  - IMAP settings default to Fastmail with folder `Trading/ToS Alerts`

- **[models.py](src/hvcwatch/models.py)**: Data models for type-safe ticker data
  - `TickerData`: Pydantic model containing ticker symbol, name, price, volume, logos, etc.
  - Shared across all notification platforms to avoid duplication
  - Uses field aliases (e.g., `price` aliased from `close`)

- **[utils.py](src/hvcwatch/utils.py)**: Core utilities
  - `extract_tickers()`: Regex-based ticker extraction from email subjects
  - `is_market_hours_or_near()`: NYSE market hours validation (uses pandas-market-calendars)
  - `get_ticker_details()`, `get_ticker_stats()`: Polygon.io API integration
  - Market data uses Polars for efficient dataframe operations

- **[email_monitor.py](src/hvcwatch/email_monitor.py)**: IMAP monitoring
  - Uses imap-tools library with IDLE protocol for real-time monitoring
  - Processes unread messages on startup
  - Continuously polls for new messages

- **[notification.py](src/hvcwatch/notification.py)**: Multi-platform notification system
  - **`NotificationProvider` Protocol**: Defines interface for all notifiers (duck typing)
  - **`DiscordNotifier`**: Discord webhook integration
    - Creates rich embeds with ticker details, logos, and company info
    - Formats volume data with human-readable suffixes (K/M/B)
    - Compares current volume to 20-day SMA
  - **`MastodonNotifier`**: Mastodon API integration
    - Posts text statuses with emojis (🔔 💰 📊) and hashtags
    - Handles character limits (450 chars with truncation)
    - Configurable server URL and access token
  - **`notify_all_platforms()`**: Orchestrator function
    - Fetches ticker data once from Polygon.io
    - Sends to all enabled platforms (checks credentials)
    - Graceful error handling (one platform can fail without affecting others)
    - Logs success/failure per platform separately

## Development Commands

```bash
# Run all checks (lint, test, typecheck)
make all

# Individual commands
make test          # Run pytest with coverage
make lint          # Format code with ruff
make typecheck     # Run pyright on src/

# Specific test commands
uv run pytest                              # All tests
uv run pytest tests/test_utils.py         # Single test file
uv run pytest tests/test_utils.py::test_extract_tickers  # Single test
uv run pytest -k "market_hours"           # Tests matching pattern
```

## Running the Bot

```bash
# Ensure .env file exists with required credentials
uv run hvcwatch  # Entry point defined in pyproject.toml
```

## Testing

- **pytest** configured in [pyproject.toml](pyproject.toml) with coverage, branch coverage, and HTML reports
- **Test environment variables** defined in `[tool.pytest.ini_options]` section (dummy values)
- Tests use mocking for external services (IMAP, Polygon.io, Discord webhooks)
- Coverage reports generated in `htmlcov/` directory

## Dependencies & Tooling

- **uv**: Package/project manager (replaces pip/venv)
- **Python**: 3.13 (specified in `.python-version`)
- **Key libraries**: pydantic-settings, structlog, imap-tools, polygon-api-client, discord-webhook, mastodon-py, polars
- **Dev tools**: pyright, pytest, ruff

## Important Implementation Details

- **Ticker extraction** filters out symbols containing "/" (e.g., options spreads)
- **Market hours** checks include 1-hour buffer before/after market open/close
- **Volume calculations** require 20-day history; handles `None` gracefully when insufficient data
- **Timezone handling**: All market time logic normalized to America/New_York
- **Logo URLs**: Fetched from stocktitan.net (not Polygon.io)

## Multi-Platform Architecture

### Protocol-Based Design

The notification system uses Python's `typing.Protocol` for duck typing, making it easy to add new platforms:

```python
class NotificationProvider(Protocol):
    def send(self, ticker_data: TickerData) -> None:
        ...
```

Any class implementing a `send()` method that accepts `TickerData` can be used as a notifier.

### Benefits

- **Zero Code Duplication**: Ticker data fetched once, shared across all platforms
- **Type Safety**: `TickerData` Pydantic model ensures consistent data structure
- **Easy Extensibility**: Add new platforms (Slack, Telegram, etc.) by implementing the protocol
- **Graceful Degradation**: Missing credentials skip that platform; one platform failing doesn't block others
- **Independent Testing**: Each notifier can be tested in isolation with mocks

### Platform Configuration

- **Discord**: Required (`DISCORD_WEBHOOK_URL` must be set)
- **Mastodon**: Optional (both `MASTODON_SERVER_URL` and `MASTODON_ACCESS_TOKEN` must be set)
- If no platforms configured, logs warning but doesn't crash

### Adding New Platforms

To add a new notification platform (e.g., Slack):

1. Create a new class in `notification.py` (e.g., `SlackNotifier`)
2. Implement `send(self, ticker_data: TickerData) -> None` method
3. Add configuration fields to `config.py` (e.g., `SLACK_WEBHOOK_URL`)
4. Update `notify_all_platforms()` to check config and instantiate notifier
5. Add comprehensive tests following existing patterns

The protocol-based design ensures type checking works without explicit inheritance.