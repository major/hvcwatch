import logging
import re
from datetime import date, datetime, timedelta
from typing import Literal

import pandas_market_calendars as mcal
import polars as pl
import pytz
import structlog
from polygon import RESTClient

from hvcwatch.config import settings

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


def format_number(num: float | int | None) -> str:
    """Format large numbers with K, M, B suffixes"""
    if num is None:
        return "N/A"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num / 1_000_000:.0f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.0f}K"
    else:
        return str(int(num))


def extract_tickers(subject: str) -> list[str]:
    logger.info("Extracting tickers", subject=subject)
    pattern = r"symbols?:\s*([\w/,\s]+)\s+(?:were|was)\s+added"
    tickers_re = re.compile(pattern, re.IGNORECASE)
    match = tickers_re.search(subject)

    if match:
        tickers = [
            x.strip().upper() for x in match.group(1).split(",") if "/" not in x.strip()
        ]
        logger.info("Extracted tickers", tickers=tickers)
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


def get_ticker_logo(ticker: str) -> str:
    logger.info("Fetching ticker logo", ticker=ticker)
    return f"https://static.stocktitan.net/company-logo/{ticker.lower()}.webp"


def get_ticker_details(ticker: str) -> dict:
    logger.info("Fetching ticker details", ticker=ticker)
    client = RESTClient(api_key=settings.polygon_api_key)
    snapshot = client.get_ticker_details(ticker)

    return {
        "ticker": snapshot.ticker,  # type: ignore
        "name": snapshot.name,  # type: ignore
        "logo_url": get_ticker_logo(ticker),
        "description": snapshot.description,  # type: ignore
        "type": snapshot.type,  # type: ignore
    }


def get_ticker_stats(ticker: str) -> dict:
    logger.info("Fetching quote for ticker", ticker=ticker)
    client = RESTClient(api_key=settings.polygon_api_key)

    start_date = date.today().strftime("%Y-%m-%d")
    end_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    aggs = []
    for a in client.list_aggs(
        ticker, 1, "day", end_date, start_date, adjusted=True, sort="asc"
    ):
        aggs.append(a)

    df = (
        pl.DataFrame([x for x in aggs])
        .select("close", "volume")
        .with_columns(pl.col("volume").rolling_mean(window_size=20).alias("volume_sma"))
        .with_columns((pl.col("volume") / pl.col("volume_sma")).alias("volume_ratio"))
    )

    last_row = df[-1]
    return {
        "close": last_row["close"].item(),
        "volume": last_row["volume"].item(),
        "volume_sma": last_row["volume_sma"].item(),
        "volume_ratio": last_row["volume_ratio"].item(),
    }


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
