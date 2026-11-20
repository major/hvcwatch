"""SQLite database for HVC alert tracking.

Allows at most one alert per ticker, per timeframe, per calendar day. 📅
Each timeframe is tracked on its own, so a daily alert never blocks a weekly
one. It also stores the IMAP position for each folder, so mail is processed
once without writing to the server.
"""

import logging
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from hvcwatch import config
from hvcwatch.types import Timeframe

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hvc_alerts (
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    alert_date DATE NOT NULL,
    PRIMARY KEY (ticker, timeframe, alert_date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_timeframe ON hvc_alerts(ticker, timeframe);
CREATE TABLE IF NOT EXISTS mailbox_cursor (
    folder TEXT PRIMARY KEY,
    uidvalidity INTEGER NOT NULL,
    last_uid INTEGER NOT NULL
);
"""


def _get_db_path() -> Path:
    """Get database path from settings or default to ~/.hvcwatch/alerts.db.

    An unset or empty HVCWATCH_DB_PATH uses the default. The parent directory
    is created for either path so sqlite can open the file. 📁
    """
    settings = config.get_settings()
    if settings.hvcwatch_db_path:
        db_path = Path(settings.hvcwatch_db_path)
    else:
        db_path = Path.home() / ".hvcwatch" / "alerts.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _get_connection() -> sqlite3.Connection:
    """Get connection and ensure schema exists."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)

    # Ensure schema exists
    conn.executescript(_SCHEMA)
    conn.commit()

    return conn


def get_cursor(folder: str) -> tuple[int, int] | None:
    """
    Get the saved IMAP position for a folder.

    Args:
        folder: IMAP folder name (e.g., "Trading/ToS Alerts")

    Returns:
        (uidvalidity, last_uid) if the folder was saved before, otherwise None
    """
    with closing(_get_connection()) as conn:
        row = conn.execute(
            "SELECT uidvalidity, last_uid FROM mailbox_cursor WHERE folder = ?",
            (folder,),
        ).fetchone()

    if row is None:
        return None
    return row[0], row[1]


def save_cursor(folder: str, uidvalidity: int, last_uid: int) -> None:
    """
    Save the IMAP position for a folder, replacing any earlier position.

    Args:
        folder: IMAP folder name (e.g., "Trading/ToS Alerts")
        uidvalidity: The folder's UIDVALIDITY the UIDs belong to
        last_uid: The highest UID already processed
    """
    with closing(_get_connection()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO mailbox_cursor (folder, uidvalidity, last_uid) VALUES (?, ?, ?)",
            (folder, uidvalidity, last_uid),
        )
        conn.commit()


def should_alert(ticker: str, timeframe: Timeframe, alert_date: date) -> bool:
    """
    Check if an alert should be sent for this ticker, timeframe, and day.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        alert_date: Date of the incoming alert

    Returns:
        False if an alert with the same ticker, timeframe, and alert_date is
        already recorded, otherwise True

    Logic:
        - Key is (ticker uppercased, timeframe, alert_date)
        - Same rule for every timeframe, with no weekly or monthly windows
    """
    with closing(_get_connection()) as conn:
        row = conn.execute(
            "SELECT 1 FROM hvc_alerts WHERE ticker = ? AND timeframe = ? AND alert_date = ?",
            (ticker.upper(), timeframe, alert_date.isoformat()),
        ).fetchone()

    # 🔁 A row for this exact key means the alert already went out today
    should_send = row is None
    logger.debug(
        "Dedup check ticker=%s timeframe=%s alert_date=%s should_alert=%s",
        ticker,
        timeframe,
        alert_date,
        should_send,
    )
    return should_send


def record_alert(ticker: str, timeframe: Timeframe, alert_date: date) -> None:
    """
    Record that an alert was sent, so the same day is not alerted again.

    Every timeframe is stored, including daily. Recording the same key twice
    keeps one row.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        timeframe: Alert timeframe ("daily", "weekly", or "monthly")
        alert_date: Date the alert was sent
    """
    with closing(_get_connection()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO hvc_alerts (ticker, timeframe, alert_date) VALUES (?, ?, ?)",
            (ticker.upper(), timeframe, alert_date.isoformat()),
        )
        conn.commit()
        logger.debug(
            "Recorded alert ticker=%s timeframe=%s alert_date=%s",
            ticker,
            timeframe,
            alert_date,
        )
