import logging
import re
from datetime import date, datetime, timedelta

import pandas_market_calendars as mcal
import polars as pl
import pytz
import structlog
from polygon import RESTClient

from hvcwatch.config import settings

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


def format_number(num: float | int) -> str:
    """Format large numbers with K, M, B suffixes"""
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
        ticker,
        1,
        "day",
        end_date,
        start_date,
        adjusted=True,
        sort="asc",
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


def is_market_hours_or_near(check_time: datetime = datetime.now(), hours: int = 3):
    """
    Returns True if the NYSE market is open or if the specified time
    (in NYC timezone) is within the specified hours of market open or close.

    Args:
        check_time: Datetime to check. If None, uses current time (default: None)
        hours: Number of hours before/after market open/close to consider "near" (default: 3)

    Returns:
        bool: True if market is open or within specified hours of open/close, False otherwise
    """
    # Get NYC timezone
    nyc_tz = pytz.timezone("America/New_York")

    # Ensure the provided time is timezone-aware and in NYC timezone
    if check_time.tzinfo is None:
        # If naive datetime, assume it's in NYC timezone
        check_time = nyc_tz.localize(check_time)
    else:
        # Convert to NYC timezone
        check_time = check_time.astimezone(nyc_tz)

    current_time = check_time

    # Get NYSE calendar
    nyse = mcal.get_calendar("NYSE")

    # Get market schedule for today
    # We need to check a range that includes today
    start_date = current_time.date()
    end_date = start_date + timedelta(days=1)

    # Get the market schedule (returns pandas DataFrame)
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)

    # If schedule is empty, market is closed today
    if schedule.empty:
        return False

    # Convert pandas DataFrame to polars for consistency with rest of codebase
    # Extract the timestamps and convert to native Python datetime
    market_open = schedule.iloc[0]["market_open"].to_pydatetime()
    market_close = schedule.iloc[0]["market_close"].to_pydatetime()

    # Check if market is currently open
    if market_open <= current_time <= market_close:
        return True

    # Check if within specified hours before market open
    hours_before_open = market_open - timedelta(hours=hours)
    if hours_before_open <= current_time < market_open:
        return True

    # Check if within specified hours after market close
    hours_after_close = market_close + timedelta(hours=hours)
    if market_close < current_time <= hours_after_close:
        return True

    return False
