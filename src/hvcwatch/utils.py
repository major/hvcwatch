import re
from datetime import date, datetime, timedelta
from typing import Literal

import pandas_market_calendars as mcal
import pytz

from hvcwatch.logging import logger


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


def extract_timeframe(subject: str) -> Literal["daily", "weekly", "monthly"]:
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
    nyc_tz = pytz.timezone("America/New_York")

    if check_time.tzinfo is None:
        # If naive datetime, assume it's in NYC timezone
        return nyc_tz.localize(check_time)
    else:
        # Convert to NYC timezone
        return check_time.astimezone(nyc_tz)


def _get_market_schedule(target_date: date) -> tuple[datetime, datetime] | None:
    """
    Get market open and close times for a specific date.

    Returns:
        tuple[datetime, datetime] | None: (market_open, market_close) or None if market is closed
    """
    nyse = mcal.get_calendar("NYSE")

    # Get the market schedule for the target date
    schedule = nyse.schedule(
        start_date=target_date, end_date=target_date + timedelta(days=1)
    )

    # If schedule is empty, market is closed that day
    if schedule.empty:
        return None

    # Extract the timestamps and convert to native Python datetime
    market_open = schedule.iloc[0]["market_open"].to_pydatetime()
    market_close = schedule.iloc[0]["market_close"].to_pydatetime()

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
