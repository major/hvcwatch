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
5. **Discord Notification** ([notification.py](src/hvcwatch/notification.py)) sends formatted embeds with enriched data

### Key Components

- **[config.py](src/hvcwatch/config.py)**: Pydantic Settings for environment variables (`.env` file)
  - Required: `FASTMAIL_USER`, `FASTMAIL_PASS`, `DISCORD_WEBHOOK_URL`, `POLYGON_API_KEY`
  - IMAP settings default to Fastmail with folder `Trading/ToS Alerts`

- **[utils.py](src/hvcwatch/utils.py)**: Core utilities
  - `extract_tickers()`: Regex-based ticker extraction from email subjects
  - `is_market_hours_or_near()`: NYSE market hours validation (uses pandas-market-calendars)
  - `get_ticker_details()`, `get_ticker_stats()`: Polygon.io API integration
  - Market data uses Polars for efficient dataframe operations

- **[email_monitor.py](src/hvcwatch/email_monitor.py)**: IMAP monitoring
  - Uses imap-tools library with IDLE protocol for real-time monitoring
  - Processes unread messages on startup
  - Continuously polls for new messages

- **[notification.py](src/hvcwatch/notification.py)**: Discord integration
  - Creates DiscordEmbed with ticker details
  - Formats volume data with human-readable suffixes (K/M/B)
  - Compares current volume to 20-day SMA

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
- **Key libraries**: pydantic-settings, structlog, imap-tools, polygon-api-client, discord-webhook, polars
- **Dev tools**: pyright, pytest, ruff

## Important Implementation Details

- **Ticker extraction** filters out symbols containing "/" (e.g., options spreads)
- **Market hours** checks include 1-hour buffer before/after market open/close
- **Volume calculations** require 20-day history; handles `None` gracefully when insufficient data
- **Timezone handling**: All market time logic normalized to America/New_York
- **Logo URLs**: Fetched from stocktitan.net (not Polygon.io)