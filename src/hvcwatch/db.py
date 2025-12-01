"""SQLite database for HVC alert tracking.

Prevents duplicate alerts for weekly/monthly HVC timeframes by tracking
when alerts were last sent for each ticker.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from hvcwatch.config import settings
from hvcwatch.logging import logger

TimeframeType = Literal["daily", "weekly", "monthly"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hvc_alerts (
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    alert_date DATE NOT NULL,
    PRIMARY KEY (ticker, timeframe, alert_date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_timeframe ON hvc_alerts(ticker, timeframe);
"""


def _get_db_path() -> Path:
    """Get database path from settings or default to ~/.hvcwatch/alerts.db."""
    if settings.hvcwatch_db_path:
        return Path(settings.hvcwatch_db_path)

    default_dir = Path.home() / ".hvcwatch"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir / "alerts.db"


def _get_connection() -> sqlite3.Connection:
    """Get connection and ensure schema exists."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)

    # Ensure schema exists
    conn.executescript(_SCHEMA)
    conn.commit()

    return conn


def _get_week_monday(d: date) -> date:
    """Get the Monday of the week containing the given date."""
    return d - timedelta(days=d.weekday())


def should_alert(ticker: str, timeframe: TimeframeType, alert_date: date) -> bool:
    """
    Check if alert should be sent for this ticker/timeframe combination.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        alert_date: Date of the incoming alert

    Returns:
        True if alert should be sent, False if it should be suppressed

    Logic:
        - Daily: Always returns True (no deduplication)
        - Weekly: True if no alert in same calendar week (Monday-based)
        - Monthly: True if no alert in same calendar month
    """
    if timeframe == "daily":
        return True

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "SELECT alert_date FROM hvc_alerts WHERE ticker = ? AND timeframe = ? ORDER BY alert_date DESC LIMIT 1",
            (ticker.upper(), timeframe),
        )
        row = cursor.fetchone()

        if row is None:
            # No previous alert - allow
            logger.debug(
                "No previous alert found ticker={ticker} timeframe={timeframe}",
                ticker=ticker,
                timeframe=timeframe,
            )
            return True

        last_alert_date = date.fromisoformat(row[0])

        if timeframe == "weekly":
            # Compare Monday of each week
            last_monday = _get_week_monday(last_alert_date)
            current_monday = _get_week_monday(alert_date)
            should_send = last_monday != current_monday
            logger.debug(
                "Weekly dedup check ticker={ticker} last_alert={last_alert} last_monday={last_monday} current_monday={current_monday} should_alert={should_alert}",
                ticker=ticker,
                last_alert=str(last_alert_date),
                last_monday=str(last_monday),
                current_monday=str(current_monday),
                should_alert=should_send,
            )
            return should_send

        elif timeframe == "monthly":
            # Compare (year, month) tuples
            should_send = (last_alert_date.year, last_alert_date.month) != (
                alert_date.year,
                alert_date.month,
            )
            logger.debug(
                "Monthly dedup check ticker={ticker} last_alert={last_alert} current_date={current_date} should_alert={should_alert}",
                ticker=ticker,
                last_alert=str(last_alert_date),
                current_date=str(alert_date),
                should_alert=should_send,
            )
            return should_send

        return True  # Fallback for unknown timeframes
    finally:
        conn.close()


def record_alert(ticker: str, timeframe: TimeframeType, alert_date: date) -> None:
    """
    Record that an alert was sent for tracking purposes.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        alert_date: Date the alert was sent
    """
    if timeframe == "daily":
        # Don't track daily alerts - they're not deduplicated
        return

    conn = _get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO hvc_alerts (ticker, timeframe, alert_date) VALUES (?, ?, ?)",
            (ticker.upper(), timeframe, alert_date.isoformat()),
        )
        conn.commit()
        logger.debug(
            "Recorded alert ticker={ticker} timeframe={timeframe} alert_date={alert_date}",
            ticker=ticker,
            timeframe=timeframe,
            alert_date=str(alert_date),
        )
    finally:
        conn.close()
