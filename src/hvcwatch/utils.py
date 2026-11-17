import logging
import re
from datetime import date, datetime, timedelta
from functools import cache
from typing import NamedTuple
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import httpx2
from exchange_calendars.errors import DateOutOfBounds

from hvcwatch import config
from hvcwatch.types import Timeframe

logger = logging.getLogger(__name__)

MASSIVE_TICKER_URL = "https://api.massive.com/v3/reference/tickers/{ticker}"
MASSIVE_TIMEOUT_SECONDS = 10


class TickerOverview(NamedTuple):
    """📇 The fields we use from a Massive ticker overview. None means unknown."""

    name: str | None
    type: str | None


@cache
def _lookup_ticker_overview(ticker: str) -> TickerOverview:
    """
    Fetch the name and type for a ticker from the Massive ticker overview endpoint.

    Results are cached per ticker, so each symbol costs one HTTP call per
    process, and company name and ticker type share that call. A 404 (unknown
    ticker) is cached as an empty overview. Any other failure raises, so
    transient errors are never cached and the next call retries.

    Args:
        ticker: Uppercase ticker symbol (e.g., "AAPL")

    Returns:
        TickerOverview with name and type. Both are None for a 404. A missing
        or empty type is None, and the name is still returned.

    Raises:
        httpx2.HTTPError: Network error, timeout, or non-2xx status
        KeyError: Response JSON is missing results.name
        ValueError: Response body is not valid JSON
    """
    # 🔐 The key goes in the header, never the URL, so it stays out of logs
    response = httpx2.get(
        MASSIVE_TICKER_URL.format(ticker=ticker),
        headers={"Authorization": f"Bearer {config.get_settings().massive_api_key}"},
        timeout=MASSIVE_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        logger.info("Ticker not found on Massive ticker=%s", ticker)
        return TickerOverview(name=None, type=None)
    response.raise_for_status()
    results = response.json()["results"]
    # 🛟 Type is optional: a missing type must not throw away a valid name
    return TickerOverview(name=results["name"], type=results.get("type") or None)


def _fetch_overview(ticker: str, lookup: str) -> TickerOverview | None:
    """
    Return the Massive overview for a ticker, or None if it cannot be fetched.

    Never raises. Name and type are optional in notifications, so a missing
    API key or any failure is logged and returns None.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        lookup: Label for log lines, such as "company name" or "ticker type"

    Returns:
        TickerOverview if the lookup worked, None otherwise
    """
    if not config.get_settings().massive_api_key:
        logger.warning("Massive API key not set, skipping %s lookup", lookup)
        return None

    try:
        return _lookup_ticker_overview(ticker.upper())
    except Exception as e:  # 🛡️ Broad catch: a notification must still be sent
        logger.warning(
            "%s lookup failed ticker=%s error=%s",
            lookup.capitalize(),
            ticker,
            str(e),
        )
        return None


def get_company_name(ticker: str) -> str | None:
    """
    Look up company name for a ticker symbol using the Massive API.

    Never raises. Company names are optional in notifications, so any
    failure is logged and returns None.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Company name if found (e.g., "Apple Inc."), None otherwise
    """
    overview = _fetch_overview(ticker, "company name")
    return None if overview is None else overview.name


def get_ticker_type(ticker: str) -> str | None:
    """
    Look up the security type code for a ticker using the Massive API.

    Codes are returned as Massive sends them, such as "CS" (common stock),
    "ETF", or "ADRC". The type shares the cached overview lookup with
    get_company_name, so each ticker costs one HTTP call per process. Never raises: the type is
    optional in notifications, so any failure is logged and returns None.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Type code if found (e.g., "CS"), None otherwise
    """
    overview = _fetch_overview(ticker, "ticker type")
    return None if overview is None else overview.type


def extract_tickers(subject: str) -> list[str]:
    logger.info("Extracting tickers subject=%s", subject)
    pattern = r"symbols?:\s*([\w/,\s]+)\s+(?:were|was)\s+added"
    tickers_re = re.compile(pattern, re.IGNORECASE)
    match = tickers_re.search(subject)

    if match:
        tickers = [
            x.strip().upper() for x in match.group(1).split(",") if "/" not in x.strip()
        ]
        logger.info("Extracted tickers tickers=%s", tickers)
        return tickers
    else:
        logger.info("No tickers found in subject")
        return []


def extract_timeframe(subject: str) -> Timeframe:
    """
    Extract HVC timeframe from email subject.

    Args:
        subject: Email subject line to parse

    Returns:
        "weekly" if subject contains "weekly"
        "monthly" if subject contains "monthly"
        "daily" otherwise (default)

    Examples:
        "...added to HVC Weekly" -> "weekly"
        "...added to HVC Monthly" -> "monthly"
        "...added to HVC" -> "daily"
    """
    subject_lower = subject.lower()
    if "weekly" in subject_lower:
        return "weekly"
    elif "monthly" in subject_lower:
        return "monthly"
    return "daily"


def _normalize_to_nyc_timezone(check_time: datetime) -> datetime:
    """Convert a datetime to NYC timezone, handling both naive and timezone-aware datetimes."""
    nyc_tz = ZoneInfo("America/New_York")

    if check_time.tzinfo is None:
        # If naive datetime, assume it's in NYC timezone
        return check_time.replace(tzinfo=nyc_tz)
    else:
        # Convert to NYC timezone
        return check_time.astimezone(nyc_tz)


@cache
def _get_nyse_calendar() -> xcals.ExchangeCalendar:
    """Get cached NYSE calendar instance."""
    return xcals.get_calendar("XNYS")


def _get_market_schedule(target_date: date) -> tuple[datetime, datetime] | None:
    """
    Get market open and close times for a specific date.

    Returns:
        tuple[datetime, datetime] | None: (market_open, market_close) or None if market is closed
    """
    nyse = _get_nyse_calendar()

    if not nyse.is_session(target_date):
        return None

    # .to_pydatetime() converts pandas Timestamp to stdlib datetime
    market_open = nyse.session_open(target_date).to_pydatetime()
    market_close = nyse.session_close(target_date).to_pydatetime()

    return market_open, market_close


def _is_time_in_range(
    target_time: datetime, start_time: datetime, end_time: datetime
) -> bool:
    """Check if target_time falls within the range [start_time, end_time]."""
    return start_time <= target_time <= end_time


def is_market_hours_or_near(check_time: datetime, hours: int = 1) -> bool:
    """
    Returns True if the NYSE market is open or if the specified time
    (in NYC timezone) is within the specified hours of market open or close.

    Args:
        check_time: Datetime to check. Required, so callers decide which clock to use.
        hours: Number of hours before/after market open/close to consider "near" (default: 1)

    Returns:
        bool: True if market is open or within specified hours of open/close, False otherwise.
            Also False, with a warning, when the date is outside the NYSE calendar range.
    """
    # Normalize to NYC timezone
    nyc_time = _normalize_to_nyc_timezone(check_time)

    # Get market schedule for the date
    try:
        market_schedule = _get_market_schedule(nyc_time.date())
    except DateOutOfBounds:
        # 📭 imap_tools reports a missing or unparseable Date as 1900-01-01, which
        # is far before the calendar start. One bad email must not stop the monitor.
        logger.warning(
            "Check time is outside the NYSE calendar range check_time=%s",
            check_time.isoformat(),
        )
        return False
    if market_schedule is None:
        return False  # Market is closed (holiday)

    market_open, market_close = market_schedule

    # Check if market is currently open
    if _is_time_in_range(nyc_time, market_open, market_close):
        return True

    # Create time ranges for "near" market hours
    hours_delta = timedelta(hours=hours)
    pre_market_start = market_open - hours_delta
    post_market_end = market_close + hours_delta

    # Check if within specified hours before market open or after market close
    return _is_time_in_range(
        nyc_time, pre_market_start, market_open - timedelta(microseconds=1)
    ) or _is_time_in_range(
        nyc_time, market_close + timedelta(microseconds=1), post_market_end
    )
