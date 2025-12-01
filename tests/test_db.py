"""Tests for HVC alert database operations."""

from datetime import date
from unittest.mock import patch

import pytest

from hvcwatch.db import (
    _get_week_monday,
    record_alert,
    should_alert,
)


@pytest.fixture
def temp_db(tmp_path):
    """Use a temporary database for each test."""
    db_path = tmp_path / "test_alerts.db"
    with patch("hvcwatch.db.settings") as mock_settings:
        mock_settings.hvcwatch_db_path = str(db_path)
        yield db_path


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


class TestShouldAlertDaily:
    """Test cases for daily timeframe (always alert)."""

    def test_daily_always_alerts(self, temp_db):
        """Daily timeframe should always return True."""
        assert should_alert("AAPL", "daily", date.today()) is True
        # Even after recording, daily should still alert
        record_alert("AAPL", "daily", date.today())
        assert should_alert("AAPL", "daily", date.today()) is True


class TestShouldAlertWeekly:
    """Test cases for weekly timeframe deduplication."""

    def test_weekly_first_alert_allowed(self, temp_db):
        """First weekly alert for a ticker should be allowed."""
        assert should_alert("AAPL", "weekly", date(2024, 12, 2)) is True

    def test_weekly_same_week_suppressed(self, temp_db):
        """Second weekly alert in same week should be suppressed."""
        monday = date(2024, 12, 2)
        tuesday = date(2024, 12, 3)

        # First alert on Monday
        assert should_alert("AAPL", "weekly", monday) is True
        record_alert("AAPL", "weekly", monday)

        # Second alert on Tuesday (same week) should be suppressed
        assert should_alert("AAPL", "weekly", tuesday) is False

    def test_weekly_new_week_allowed(self, temp_db):
        """Weekly alert in new week should be allowed."""
        monday_week1 = date(2024, 12, 2)
        monday_week2 = date(2024, 12, 9)

        # Alert in week 1
        assert should_alert("AAPL", "weekly", monday_week1) is True
        record_alert("AAPL", "weekly", monday_week1)

        # Alert in week 2 should be allowed
        assert should_alert("AAPL", "weekly", monday_week2) is True

    def test_weekly_different_tickers_independent(self, temp_db):
        """Different tickers should be tracked independently."""
        monday = date(2024, 12, 2)

        # Alert AAPL
        assert should_alert("AAPL", "weekly", monday) is True
        record_alert("AAPL", "weekly", monday)

        # MSFT should still be allowed on same day
        assert should_alert("MSFT", "weekly", monday) is True


class TestShouldAlertMonthly:
    """Test cases for monthly timeframe deduplication."""

    def test_monthly_first_alert_allowed(self, temp_db):
        """First monthly alert for a ticker should be allowed."""
        assert should_alert("AAPL", "monthly", date(2024, 12, 1)) is True

    def test_monthly_same_month_suppressed(self, temp_db):
        """Second monthly alert in same month should be suppressed."""
        dec_1 = date(2024, 12, 1)
        dec_15 = date(2024, 12, 15)

        # First alert on Dec 1
        assert should_alert("AAPL", "monthly", dec_1) is True
        record_alert("AAPL", "monthly", dec_1)

        # Second alert on Dec 15 (same month) should be suppressed
        assert should_alert("AAPL", "monthly", dec_15) is False

    def test_monthly_new_month_allowed(self, temp_db):
        """Monthly alert in new month should be allowed."""
        dec = date(2024, 12, 15)
        jan = date(2025, 1, 5)

        # Alert in December
        assert should_alert("AAPL", "monthly", dec) is True
        record_alert("AAPL", "monthly", dec)

        # Alert in January should be allowed
        assert should_alert("AAPL", "monthly", jan) is True

    def test_monthly_year_change(self, temp_db):
        """Monthly should handle year changes correctly."""
        dec_2024 = date(2024, 12, 31)
        jan_2025 = date(2025, 1, 1)

        record_alert("AAPL", "monthly", dec_2024)
        # Next day is new month AND new year
        assert should_alert("AAPL", "monthly", jan_2025) is True


class TestTimeframeIndependence:
    """Test that different timeframes are tracked independently."""

    def test_weekly_and_monthly_independent(self, temp_db):
        """Same ticker can alert for both weekly AND monthly on same day."""
        today = date(2024, 12, 2)

        # Record weekly alert
        assert should_alert("AAPL", "weekly", today) is True
        record_alert("AAPL", "weekly", today)

        # Monthly should still be allowed (different timeframe)
        assert should_alert("AAPL", "monthly", today) is True
        record_alert("AAPL", "monthly", today)

        # Both should now be suppressed for same period
        assert should_alert("AAPL", "weekly", today) is False
        assert should_alert("AAPL", "monthly", today) is False


class TestRecordAlert:
    """Test cases for record_alert function."""

    def test_record_alert_creates_entry(self, temp_db):
        """Recording an alert should create a database entry."""
        today = date(2024, 12, 2)

        # First check should allow
        assert should_alert("AAPL", "weekly", today) is True

        # Record it
        record_alert("AAPL", "weekly", today)

        # Now it should be suppressed
        assert should_alert("AAPL", "weekly", today) is False

    def test_record_alert_daily_no_op(self, temp_db):
        """Recording daily alerts should be a no-op (not tracked)."""
        today = date.today()

        record_alert("AAPL", "daily", today)
        # Daily should still alert (not tracked)
        assert should_alert("AAPL", "daily", today) is True

    def test_record_alert_case_insensitive(self, temp_db):
        """Ticker symbols should be stored uppercase."""
        today = date(2024, 12, 2)

        # Record with lowercase
        record_alert("aapl", "weekly", today)

        # Check with uppercase should be suppressed
        assert should_alert("AAPL", "weekly", today) is False


class TestDatabasePath:
    """Test database path configuration."""

    def test_uses_configured_path(self, tmp_path):
        """Should use path from settings when configured."""
        db_path = tmp_path / "custom.db"
        with patch("hvcwatch.db.settings") as mock_settings:
            mock_settings.hvcwatch_db_path = str(db_path)

            # Trigger database creation
            record_alert("TEST", "weekly", date.today())

            # Verify file was created at custom path
            assert db_path.exists()

    def test_uses_default_path_when_not_configured(self, tmp_path):
        """Should use default ~/.hvcwatch/alerts.db when not configured."""
        with (
            patch("hvcwatch.db.settings") as mock_settings,
            patch("hvcwatch.db.Path.home") as mock_home,
        ):
            mock_settings.hvcwatch_db_path = None
            mock_home.return_value = tmp_path

            # Trigger database creation
            record_alert("TEST", "weekly", date.today())

            # Verify file was created at default path
            expected_path = tmp_path / ".hvcwatch" / "alerts.db"
            assert expected_path.exists()
