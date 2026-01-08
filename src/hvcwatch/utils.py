import json
import re
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from hvcwatch.logging import logger
from hvcwatch.types import Timeframe

# Path to SEC company tickers data file
SEC_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "company_tickers.json"


@cache
def _load_sec_ticker_lookup() -> dict[str, str]:
    """
    Load SEC company tickers data and build ticker->name lookup.

    Returns a dict mapping ticker symbols to company names.
    Uses LRU cache to avoid reloading the file on every lookup.
    """
    if not SEC_DATA_PATH.exists():
        logger.warning("SEC data file not found path={path}", path=SEC_DATA_PATH)
        return {}

    try:
        with open(SEC_DATA_PATH) as f:
            data = json.load(f)
        # Build ticker -> title lookup
        lookup = {entry["ticker"]: entry["title"] for entry in data.values()}
        logger.info("Loaded SEC ticker data entries={count}", count=len(lookup))
        return lookup
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to parse SEC data error={error}", error=str(e))
        return {}


def get_company_name(ticker: str) -> str | None:
    """
    Look up company name for a ticker symbol using SEC data.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")

    Returns:
        Company name if found (e.g., "Apple Inc."), None otherwise
    """
    lookup = _load_sec_ticker_lookup()
    return lookup.get(ticker.upper())


def extract_tickers(subject: str) -> list[str]:
    logger.info("Extracting tickers subject={subject}", subject=subject)
    pattern = r"symbols?:\s*([\w/,\s]+)\s+(?:were|was)\s+added"
    tickers_re = re.compile(pattern, re.IGNORECASE)
    match = tickers_re.search(subject)

    if match:
        tickers = [
            x.strip().upper() for x in match.group(1).split(",") if "/" not in x.strip()
        ]
        logger.info("Extracted tickers tickers={tickers}", tickers=tickers)
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


def is_market_hours_or_near(
    check_time: datetime = datetime.now(), hours: int = 1
) -> bool:
    """
    Returns True if the NYSE market is open or if the specified time
    (in NYC timezone) is within the specified hours of market open or close.

    Args:
        check_time: Datetime to check. If None, uses current time (default: None)
        hours: Number of hours before/after market open/close to consider "near" (default: 1)

    Returns:
        bool: True if market is open or within specified hours of open/close, False otherwise
    """
    # Normalize to NYC timezone
    nyc_time = _normalize_to_nyc_timezone(check_time)

    # Get market schedule for the date
    market_schedule = _get_market_schedule(nyc_time.date())
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
