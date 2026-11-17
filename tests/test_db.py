"""Tests for HVC alert database operations.

These are sociable tests: they use the real SQLite file that the autouse
`settings` fixture places in tmp_path (see conftest.py).
"""

import sqlite3
from contextlib import closing
from datetime import date

import pytest

from hvcwatch.db import (
    _get_week_monday,
    get_cursor,
    record_alert,
    save_cursor,
    should_alert,
)

MONDAY = date(2024, 12, 2)


def count_rows(db_path) -> int:
    """🔢 Count the rows in hvc_alerts. A database with no table has zero rows."""
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            return conn.execute("SELECT COUNT(*) FROM hvc_alerts").fetchone()[0]
        except sqlite3.OperationalError:  # 📭 Table is created on first real use
            return 0


class TestGetWeekMonday:
    """Test cases for _get_week_monday helper."""

    @pytest.mark.parametrize(
        "input_date,expected_monday",
        [
            (date(2024, 12, 2), date(2024, 12, 2)),  # Monday -> Monday
            (date(2024, 12, 3), date(2024, 12, 2)),  # Tuesday -> Monday
            (date(2024, 12, 4), date(2024, 12, 2)),  # Wednesday -> Monday
            (date(2024, 12, 5), date(2024, 12, 2)),  # Thursday -> Monday
            (date(2024, 12, 6), date(2024, 12, 2)),  # Friday -> Monday
            (date(2024, 12, 7), date(2024, 12, 2)),  # Saturday -> Monday
            (date(2024, 12, 8), date(2024, 12, 2)),  # Sunday -> Monday
            (date(2024, 12, 9), date(2024, 12, 9)),  # Next Monday -> Next Monday
        ],
    )
    def test_get_week_monday(self, input_date, expected_monday):
        """Test Monday calculation for various days of the week."""
        assert _get_week_monday(input_date) == expected_monday


class TestDaily:
    """Daily alerts are never deduplicated and never stored."""

    def test_daily_always_alerts(self):
        """📅 should_alert is True for daily even when a record call came first."""
        record_alert("AAPL", "daily", MONDAY)

        assert should_alert("AAPL", "daily", MONDAY) is True

    def test_record_alert_daily_stores_nothing(self, db_path):
        """📅 record_alert on a daily alert writes no row."""
        record_alert("AAPL", "daily", MONDAY)

        assert count_rows(db_path) == 0


class TestDeduplication:
    """Weekly (Monday-based) and monthly suppression rules."""

    @pytest.mark.parametrize(
        ("timeframe", "first", "second", "expected"),
        [
            pytest.param(
                "weekly",
                date(2024, 12, 2),
                date(2024, 12, 3),
                False,
                id="weekly-same-week",
            ),
            pytest.param(
                "weekly",
                date(2024, 12, 2),
                date(2024, 12, 8),
                False,
                id="weekly-monday-to-sunday",
            ),
            pytest.param(
                "weekly",
                date(2024, 12, 8),
                date(2024, 12, 9),
                True,
                id="weekly-sunday-to-monday",
            ),
            pytest.param(
                "weekly",
                date(2024, 12, 2),
                date(2024, 12, 9),
                True,
                id="weekly-next-week",
            ),
            pytest.param(
                "monthly",
                date(2024, 12, 1),
                date(2024, 12, 15),
                False,
                id="monthly-same-month",
            ),
            pytest.param(
                "monthly",
                date(2024, 12, 15),
                date(2025, 1, 5),
                True,
                id="monthly-next-month",
            ),
            pytest.param(
                "monthly",
                date(2024, 12, 31),
                date(2025, 1, 1),
                True,
                id="monthly-year-change",
            ),
            pytest.param(
                "monthly",
                date(2024, 12, 15),
                date(2025, 12, 15),
                True,
                id="monthly-same-month-next-year",
            ),
        ],
    )
    def test_second_alert_decision(self, timeframe, first, second, expected):
        """🔁 The first alert passes, then the second follows the timeframe rule."""
        assert should_alert("AAPL", timeframe, first) is True
        record_alert("AAPL", timeframe, first)

        assert should_alert("AAPL", timeframe, second) is expected

    def test_different_tickers_are_independent(self):
        """🧍 Recording AAPL leaves MSFT allowed while AAPL stays suppressed."""
        record_alert("AAPL", "weekly", MONDAY)

        assert should_alert("MSFT", "weekly", MONDAY) is True
        assert should_alert("AAPL", "weekly", MONDAY) is False

    def test_timeframes_are_independent(self):
        """🧍 A weekly record does not suppress monthly, and the reverse."""
        record_alert("AAPL", "weekly", MONDAY)

        assert should_alert("AAPL", "monthly", MONDAY) is True

        record_alert("AAPL", "monthly", MONDAY)

        assert should_alert("AAPL", "weekly", MONDAY) is False
        assert should_alert("AAPL", "monthly", MONDAY) is False

    @pytest.mark.parametrize(
        ("timeframe", "newer", "older", "check"),
        [
            pytest.param(
                "weekly",
                date(2024, 12, 9),
                date(2024, 12, 2),
                date(2024, 12, 10),
                id="weekly",
            ),
            pytest.param(
                "monthly",
                date(2025, 1, 5),
                date(2024, 12, 2),
                date(2025, 1, 20),
                id="monthly",
            ),
        ],
    )
    def test_latest_alert_wins_when_recorded_out_of_order(
        self, timeframe, newer, older, check
    ):
        """⏪ The newest stored date decides, whatever order the rows were recorded."""
        record_alert("AAPL", timeframe, newer)
        record_alert("AAPL", timeframe, older)

        assert should_alert("AAPL", timeframe, check) is False


class TestTickerCase:
    """Ticker symbols are matched case-insensitively."""

    @pytest.mark.parametrize(
        ("recorded", "checked"),
        [("aapl", "AAPL"), ("AAPL", "aapl")],
    )
    def test_case_does_not_matter(self, recorded, checked):
        """🔠 A record under one case suppresses a check under the other."""
        record_alert(recorded, "weekly", MONDAY)

        assert should_alert(checked, "weekly", MONDAY) is False


class TestRecordAlert:
    """Test cases for record_alert storage."""

    def test_recording_the_same_key_twice_keeps_one_row(self, db_path):
        """♻️ Re-recording the same ticker, timeframe, and date does not fail or duplicate."""
        record_alert("AAPL", "weekly", MONDAY)
        record_alert("AAPL", "weekly", MONDAY)

        assert count_rows(db_path) == 1


class TestMailboxCursor:
    """The per-folder IMAP position that tracks seen mail without writing flags."""

    def test_cursor_is_stored_per_folder_and_a_save_overwrites_only_its_folder(self):
        """📌 An unset folder has no cursor, a save round-trips, and a second save replaces only its own row."""
        # Arrange
        save_cursor("Alerts", 7, 41)
        save_cursor("INBOX", 3, 5)

        # Act / Assert
        assert get_cursor("Alerts") == (7, 41)

        # Act
        save_cursor("Alerts", 8, 1)  # 🔁 A new UIDVALIDITY overwrites the old row

        # Assert
        assert get_cursor("Alerts") == (8, 1)
        assert get_cursor("INBOX") == (3, 5)
        assert get_cursor("Archive") is None


class TestDatabasePath:
    """Test database path configuration."""

    def test_uses_configured_path(self, db_path):
        """🗄️ The database is created at the path from settings."""
        record_alert("TEST", "weekly", MONDAY)

        assert db_path.exists()

    def test_creates_missing_parent_dirs_for_configured_path(
        self, tmp_path, override_settings
    ):
        """📁 A custom path whose parent directories do not exist still works."""
        nested = tmp_path / "nested" / "deeper" / "custom.db"
        override_settings(hvcwatch_db_path=str(nested))

        record_alert("TEST", "weekly", MONDAY)

        assert nested.exists()
        assert should_alert("TEST", "weekly", date(2024, 12, 3)) is False

    @pytest.mark.parametrize("configured", [None, ""], ids=["unset", "empty"])
    def test_uses_default_path_when_not_configured(
        self, tmp_path, monkeypatch, override_settings, db_path, configured
    ):
        """🏠 An unset or empty path goes under $HOME/.hvcwatch."""
        monkeypatch.setenv("HOME", str(tmp_path))
        override_settings(hvcwatch_db_path=configured)

        record_alert("TEST", "weekly", MONDAY)

        assert (tmp_path / ".hvcwatch" / "alerts.db").exists()
        assert not db_path.exists()
