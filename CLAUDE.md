# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**hvcwatch** is a bot that monitors email inbox for trading alerts from ThinkOrSwim and forwards them to Discord with enriched market data.

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
5. **Discord Notification** ([notification.py](src/hvcwatch/notification.py)) sends alerts:
   - `notify_all_platforms()` fetches data once and sends to all configured Discord webhooks
   - Discord notifier sends rich embeds with company logos
   - Supports multiple webhook URLs for different channels

### Key Components

- **[config.py](src/hvcwatch/config.py)**: Pydantic Settings for environment variables (`.env` file)
  - Required: `FASTMAIL_USER`, `FASTMAIL_PASS`, `POLYGON_API_KEY`
  - Required (Discord): Either `DISCORD_WEBHOOK_URL` (single, deprecated) or `DISCORD_WEBHOOK_URLS` (comma-separated, recommended)
  - Optional: `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` (for error tracking)
  - IMAP settings default to Fastmail with folder `Trading/ToS Alerts`
  - **Multiple Discord Webhooks**: Supports sending to multiple Discord channels via comma-separated URLs
    - Use `DISCORD_WEBHOOK_URLS="url1,url2,url3"` for multiple webhooks
    - Backward compatible: Old `DISCORD_WEBHOOK_URL` still works for single webhook
    - URLs are automatically deduplicated and whitespace-trimmed

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

- **[notification.py](src/hvcwatch/notification.py)**: Discord notification system
  - **`NotificationProvider` Protocol**: Defines interface for notifiers (duck typing)
  - **`DiscordNotifier`**: Discord webhook integration
    - Accepts webhook URL in constructor for flexible multi-webhook support
    - Creates rich embeds with ticker details, logos, and company info
    - Formats volume data with human-readable suffixes (K/M/B)
    - Compares current volume to 20-day SMA
    - **Multiple webhooks supported**: One notifier instance per webhook URL
  - **`notify_all_platforms()`**: Orchestrator function
    - Fetches ticker data once from Polygon.io
    - Creates multiple `DiscordNotifier` instances (one per webhook URL)
    - Iterates through all Discord webhooks, sending to each independently
    - Graceful error handling (one webhook can fail without affecting others)
    - Logs success/failure per webhook separately with truncated URLs

- **[main.py](src/hvcwatch/main.py)**: Application entry point
  - Initializes Sentry error tracking if `SENTRY_DSN` is provided
  - Starts email monitoring
  - Sentry breadcrumbs track key operations for better error debugging

- **[logging.py](src/hvcwatch/logging.py)**: Centralized logging configuration
  - Uses loguru for pretty, structured logging
  - Configured at INFO level by default
  - All modules import logger from here: `from hvcwatch.logging import logger`
  - Log format: `logger.info("message key={key}", key=value)` (inline templating)

## Error Tracking with Sentry 🔍

The bot integrates with Sentry.io for comprehensive error tracking and monitoring:

### Configuration

Add these optional environment variables to your `.env` file:

```bash
# Sentry.io Configuration (optional)
SENTRY_DSN=https://your-project-key@your-org.sentry.io/your-project-id
SENTRY_ENVIRONMENT=production  # or development, staging, etc. (default: production)
SENTRY_TRACES_SAMPLE_RATE=1.0  # 0.0 to 1.0 (default: 1.0)
```

### Features

- **Automatic Exception Capture**: All unhandled exceptions are automatically sent to Sentry
- **Breadcrumbs**: Key operations are tracked as breadcrumbs for better debugging context:
  - IMAP connection and monitoring events
  - Email processing and ticker extraction
  - Market data fetching from Polygon.io
  - Notification sending to Discord
- **Contextual Data**: Exceptions include local variables, stack traces, and execution context
- **Graceful Degradation**: If Sentry DSN is not configured, the bot runs normally without error tracking

### Breadcrumb Categories

The following breadcrumb categories are used throughout the application:

- `imap`: IMAP connection and email monitoring events
- `email`: Email processing, ticker extraction, and filtering
- `notification`: Ticker data fetching and notification sending

### Testing

When running tests, Sentry is automatically mocked to avoid sending test data to your Sentry project. Test fixtures in `test_main.py`, `test_email_monitor.py`, and `test_notification.py` ensure Sentry integration doesn't interfere with test execution.

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
- **Key libraries**: pydantic-settings, loguru, imap-tools, polygon-api-client, discord-webhook, polars
- **Dev tools**: pyright, pytest, ruff

## Important Implementation Details

- **Ticker extraction** filters out symbols containing "/" (e.g., options spreads)
- **Market hours** checks include 1-hour buffer before/after market open/close
- **Volume calculations** require 20-day history; handles `None` gracefully when insufficient data
- **Timezone handling**: All market time logic normalized to America/New_York
- **Logo URLs**: Fetched from stocktitan.net (not Polygon.io)

## Discord Configuration

### Webhook URLs

- **Recommended**: Use `DISCORD_WEBHOOK_URLS` for comma-separated webhook URLs
- **Legacy**: Use `DISCORD_WEBHOOK_URL` for a single webhook (deprecated but still supported)
- Both can be used together; they will be combined and deduplicated
- Example: `DISCORD_WEBHOOK_URLS="https://discord.com/api/webhooks/123/abc,https://discord.com/api/webhooks/456/def"`

### Notification Features

- Rich embeds with company name, ticker symbol, and logo
- Current price and volume data
- Volume comparison to 20-day moving average
- Graceful error handling (one webhook can fail without affecting others)