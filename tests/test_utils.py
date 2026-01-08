import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd

from hvcwatch.utils import (
    extract_tickers,
    extract_timeframe,
    get_company_name,
    is_market_hours_or_near,
    _load_sec_ticker_lookup,
    _get_nyse_calendar,
)


@pytest.fixture
def nyc_timezone():
    """NYC timezone fixture."""
    return ZoneInfo("America/New_York")


@pytest.fixture
def mock_market_times(nyc_timezone):
    """Return market open/close times as pandas Timestamps for today."""
    today = datetime.now(nyc_timezone).date()
    market_open = pd.Timestamp(
        datetime.combine(
            today, datetime.min.time().replace(hour=9, minute=30), tzinfo=nyc_timezone
        )
    )
    market_close = pd.Timestamp(
        datetime.combine(
            today, datetime.min.time().replace(hour=16, minute=0), tzinfo=nyc_timezone
        )
    )
    return market_open, market_close


class TestExtractTickers:
    """Test cases for extract_tickers function."""

    @pytest.mark.parametrize(
        "subject_line,expected",
        [
            ("Alert: New symbols: ATAI, DFSU were added to HVC.", ["ATAI", "DFSU"]),
            (
                "Alert: New symbols: CDTX, GSEW, POET were added to HVC.",
                ["CDTX", "GSEW", "POET"],
            ),
            ("Alert: New symbols: FCX, ZVRA were added to HVC.", ["FCX", "ZVRA"]),
            ("Alert: New symbol: LXEO was added to HVC.", ["LXEO"]),
            (
                "Alert: New symbol: /ZQU25, /ZZU25 were added to HVC.",
                [],
            ),  # Futures excluded
            (
                "Alert: New symbols: AAPL, /ZQU25, MSFT were added to HVC.",
                ["AAPL", "MSFT"],
            ),  # Mixed
            ("Random text without tickers", []),  # No match
            (
                "symbols: ABC, DEF, GHI were added",
                ["ABC", "DEF", "GHI"],
            ),  # Case insensitive
            ("SYMBOLS: xyz, pqr WAS ADDED", ["XYZ", "PQR"]),  # Different case
        ],
    )
    def test_extract_tickers_various_formats(self, subject_line, expected):
        """Test ticker extraction with various subject line formats."""
        result = extract_tickers(subject_line)
        assert result == expected


class TestExtractTimeframe:
    """Test cases for extract_timeframe function."""

    @pytest.mark.parametrize(
        "subject,expected",
        [
            ("Alert: New symbols: IPG, PTCT were added to HVC Weekly", "weekly"),
            ("Alert: New symbols: ABC were added to HVC Monthly", "monthly"),
            ("Alert: New symbols: XYZ were added to HVC", "daily"),
            ("Alert: New symbols: XYZ were added to HVC.", "daily"),
            ("symbols: FOO were added to HVC WEEKLY", "weekly"),  # case insensitive
            ("symbols: FOO were added to HVC weekly", "weekly"),  # lowercase
            ("symbols: BAR were added to HVC MONTHLY", "monthly"),  # uppercase
            ("HVC Monthly Alert: ABC added", "monthly"),  # Different format
            ("Weekly HVC Alert", "weekly"),  # Keyword at start
            ("Random email without timeframe", "daily"),  # Default to daily
        ],
    )
    def test_extract_timeframe(self, subject, expected):
        """Test timeframe extraction from various subject formats."""
        assert extract_timeframe(subject) == expected


class TestIsMarketHoursOrNear:
    """Test cases for is_market_hours_or_near function."""

    @pytest.fixture(autouse=True)
    def clear_calendar_cache(self):
        """Clear the calendar cache before each test."""
        _get_nyse_calendar.cache_clear()
        yield
        _get_nyse_calendar.cache_clear()

    @pytest.fixture
    def mock_calendar_open(self, mock_market_times):
        """Mock exchange calendar for an open market day."""
        market_open, market_close = mock_market_times
        with patch("hvcwatch.utils._get_nyse_calendar") as mock_get_cal:
            mock_nyse = Mock()
            mock_nyse.is_session.return_value = True
            mock_nyse.session_open.return_value = market_open
            mock_nyse.session_close.return_value = market_close
            mock_get_cal.return_value = mock_nyse
            yield mock_nyse

    @pytest.fixture
    def mock_calendar_closed(self):
        """Mock exchange calendar for a closed market day."""
        with patch("hvcwatch.utils._get_nyse_calendar") as mock_get_cal:
            mock_nyse = Mock()
            mock_nyse.is_session.return_value = False
            mock_get_cal.return_value = mock_nyse
            yield mock_nyse

    def test_market_currently_open(self, mock_calendar_open, nyc_timezone):
        """Test when market is currently open."""
        market_day = datetime.now(nyc_timezone).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=14, minute=0),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time)
        assert result is True

    def test_market_closed_but_near_open(self, mock_calendar_open, nyc_timezone):
        """Test when market is closed but within hours before open."""
        market_day = datetime.now(nyc_timezone).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=7, minute=30),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is True

    def test_market_closed_but_near_close(self, mock_calendar_open, nyc_timezone):
        """Test when market is closed but within hours after close."""
        market_day = datetime.now(nyc_timezone).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=18, minute=0),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is True

    def test_market_closed_too_far_before(self, mock_calendar_open, nyc_timezone):
        """Test when market is closed and too far before open."""
        market_day = datetime.now(nyc_timezone).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=4, minute=30),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is False

    def test_market_closed_too_far_after(self, mock_calendar_open, nyc_timezone):
        """Test when market is closed and too far after close."""
        market_day = datetime.now(nyc_timezone).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=21, minute=0),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is False

    def test_market_holiday(self, mock_calendar_closed):
        """Test when market is closed for holiday."""
        result = is_market_hours_or_near()
        assert result is False

    def test_naive_datetime_input(self, mock_calendar_open):
        """Test with naive datetime input (assumes NYC timezone)."""
        market_day = datetime.now().date()
        test_time = datetime.combine(
            market_day, datetime.min.time().replace(hour=14, minute=0)
        )

        result = is_market_hours_or_near(test_time)
        assert isinstance(result, bool)

    def test_utc_datetime_input(self, mock_calendar_open):
        """Test with UTC timezone-aware datetime input."""
        market_day = datetime.now(timezone.utc).date()
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=19, minute=0),
            tzinfo=timezone.utc,
        )

        result = is_market_hours_or_near(test_time)
        assert isinstance(result, bool)

    def test_default_datetime_is_now(self, mock_calendar_open):
        """Test that default datetime uses current time."""
        result = is_market_hours_or_near()
        assert isinstance(result, bool)

    @pytest.mark.parametrize("hours", [0, 1, 3, 6])
    def test_different_hour_buffers(self, mock_calendar_open, nyc_timezone, hours):
        """Test with different hour buffer values."""
        market_day = datetime.now(nyc_timezone).date()
        safe_hour = min(16 + min(hours, 7), 23)
        test_time = datetime.combine(
            market_day,
            datetime.min.time().replace(hour=safe_hour, minute=30),
            tzinfo=nyc_timezone,
        )

        result = is_market_hours_or_near(test_time, hours=hours)
        assert isinstance(result, bool)


class TestGetCompanyName:
    """Test cases for get_company_name function."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the LRU cache before each test."""
        _load_sec_ticker_lookup.cache_clear()
        yield
        _load_sec_ticker_lookup.cache_clear()

    def test_get_company_name_found(self, tmp_path):
        """Test getting company name for known ticker."""
        # Create mock SEC data file
        sec_data = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
        }
        data_file = tmp_path / "company_tickers.json"
        import json

        data_file.write_text(json.dumps(sec_data))

        with patch("hvcwatch.utils.SEC_DATA_PATH", data_file):
            assert get_company_name("AAPL") == "Apple Inc."
            assert get_company_name("MSFT") == "MICROSOFT CORP"

    def test_get_company_name_not_found(self, tmp_path):
        """Test getting company name for unknown ticker."""
        sec_data = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }
        data_file = tmp_path / "company_tickers.json"
        import json

        data_file.write_text(json.dumps(sec_data))

        with patch("hvcwatch.utils.SEC_DATA_PATH", data_file):
            assert get_company_name("FAKE") is None
            assert get_company_name("NOTREAL") is None

    def test_get_company_name_case_insensitive(self, tmp_path):
        """Test that ticker lookup is case insensitive."""
        sec_data = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }
        data_file = tmp_path / "company_tickers.json"
        import json

        data_file.write_text(json.dumps(sec_data))

        with patch("hvcwatch.utils.SEC_DATA_PATH", data_file):
            assert get_company_name("aapl") == "Apple Inc."
            assert get_company_name("Aapl") == "Apple Inc."
            assert get_company_name("AAPL") == "Apple Inc."

    def test_get_company_name_missing_file(self, tmp_path):
        """Test graceful handling when SEC data file is missing."""
        missing_file = tmp_path / "nonexistent.json"

        with patch("hvcwatch.utils.SEC_DATA_PATH", missing_file):
            assert get_company_name("AAPL") is None

    def test_get_company_name_invalid_json(self, tmp_path):
        """Test graceful handling when SEC data file has invalid JSON."""
        data_file = tmp_path / "company_tickers.json"
        data_file.write_text("not valid json")

        with patch("hvcwatch.utils.SEC_DATA_PATH", data_file):
            assert get_company_name("AAPL") is None
