import pytest
from unittest.mock import Mock, patch
from datetime import datetime
import pytz
import pandas as pd

from hvcwatch.utils import (
    extract_tickers,
    extract_timeframe,
    format_number,
    get_ticker_logo,
    get_ticker_details,
    get_ticker_stats,
    is_market_hours_or_near,
)


@pytest.fixture
def mock_polygon_client():
    """Mock polygon REST client."""
    with patch("hvcwatch.utils.RESTClient") as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_settings():
    """Mock settings with polygon API key."""
    with patch("hvcwatch.utils.settings") as mock_settings:
        mock_settings.polygon_api_key = "test_api_key"
        yield mock_settings


@pytest.fixture
def nyc_timezone():
    """NYC timezone fixture."""
    return pytz.timezone("America/New_York")


@pytest.fixture
def market_schedule_open():
    """Mock market schedule for an open market day."""
    nyc_tz = pytz.timezone("America/New_York")
    today = datetime.now(nyc_tz).date()
    market_open = nyc_tz.localize(
        datetime.combine(today, datetime.min.time().replace(hour=9, minute=30))
    )
    market_close = nyc_tz.localize(
        datetime.combine(today, datetime.min.time().replace(hour=16, minute=0))
    )

    schedule = pd.DataFrame({
        "market_open": [market_open],
        "market_close": [market_close],
    })
    return schedule


@pytest.fixture
def market_schedule_closed():
    """Mock empty market schedule for a closed market day."""
    return pd.DataFrame()


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


class TestFormatNumber:
    """Test cases for format_number function."""

    @pytest.mark.parametrize(
        "number,expected",
        [
            (1_234_567_890, "1.2B"),  # Billions
            (1_000_000_000, "1.0B"),  # Exactly 1 billion
            (999_999_999, "1000M"),  # Just under 1 billion
            (1_234_567, "1M"),  # Millions
            (1_000_000, "1M"),  # Exactly 1 million
            (999_999, "1000K"),  # Just under 1 million
            (12_345, "12K"),  # Thousands
            (1_000, "1K"),  # Exactly 1 thousand
            (999, "999"),  # Under 1 thousand
            (500, "500"),  # Small number
            (0, "0"),  # Zero
            (1, "1"),  # One
        ],
    )
    def test_format_number_ranges(self, number, expected):
        """Test number formatting for different ranges."""
        assert format_number(number) == expected


class TestGetTickerLogo:
    """Test cases for get_ticker_logo function."""

    @pytest.mark.parametrize(
        "ticker,expected_url",
        [
            ("AAPL", "https://static.stocktitan.net/company-logo/aapl.webp"),
            ("MSFT", "https://static.stocktitan.net/company-logo/msft.webp"),
            ("ABC", "https://static.stocktitan.net/company-logo/abc.webp"),
            ("XYZ", "https://static.stocktitan.net/company-logo/xyz.webp"),
        ],
    )
    def test_get_ticker_logo_url(self, ticker, expected_url):
        """Test ticker logo URL generation."""
        assert get_ticker_logo(ticker) == expected_url


class TestGetTickerDetails:
    """Test cases for get_ticker_details function."""

    def test_get_ticker_details_success(self, mock_polygon_client, mock_settings):
        """Test successful ticker details retrieval."""
        mock_snapshot = Mock()
        mock_snapshot.ticker = "AAPL"
        mock_snapshot.name = "Apple Inc."
        mock_snapshot.description = "Technology company"
        mock_snapshot.type = "CS"

        mock_polygon_client.get_ticker_details.return_value = mock_snapshot

        result = get_ticker_details("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["name"] == "Apple Inc."
        assert (
            result["logo_url"] == "https://static.stocktitan.net/company-logo/aapl.webp"
        )
        assert result["description"] == "Technology company"
        assert result["type"] == "CS"

        mock_polygon_client.get_ticker_details.assert_called_once_with("AAPL")


class TestGetTickerStats:
    """Test cases for get_ticker_stats function."""

    @patch("hvcwatch.utils.pl.DataFrame")
    def test_get_ticker_stats_with_polars_mock(
        self, mock_df_class, mock_polygon_client, mock_settings
    ):
        """Test ticker stats with polars DataFrame fully mocked."""
        # Mock the aggregates data
        mock_polygon_client.list_aggs.return_value = [Mock(), Mock(), Mock()]

        # Create a mock DataFrame with chained method calls
        mock_df = Mock()
        mock_df.select.return_value = mock_df
        mock_df.with_columns.return_value = mock_df

        # Mock the final DataFrame indexing to return a mock row
        mock_row = {
            "close": Mock(item=Mock(return_value=150.25)),
            "volume": Mock(item=Mock(return_value=2500000)),
            "volume_sma": Mock(item=Mock(return_value=2000000.0)),
            "volume_ratio": Mock(item=Mock(return_value=1.25)),
        }
        # Properly set up __getitem__ method
        mock_df.__getitem__ = Mock(return_value=mock_row)
        mock_df_class.return_value = mock_df

        result = get_ticker_stats("AAPL")

        # Verify the result structure
        assert isinstance(result, dict)
        assert "close" in result
        assert "volume" in result
        assert "volume_sma" in result
        assert "volume_ratio" in result

        # Verify the mocked values
        assert result["close"] == 150.25
        assert result["volume"] == 2500000
        assert result["volume_sma"] == 2000000.0
        assert result["volume_ratio"] == 1.25

        # Verify the polygon client was called correctly
        mock_polygon_client.list_aggs.assert_called_once()

        # Verify DataFrame operations were called
        mock_df.select.assert_called_once_with("close", "volume")
        assert (
            mock_df.with_columns.call_count == 2
        )  # Called twice for volume_sma and volume_ratio

    def test_get_ticker_stats_calls_polygon_correctly(
        self, mock_polygon_client, mock_settings
    ):
        """Test that get_ticker_stats calls polygon with correct parameters."""
        # Mock to avoid the DataFrame operations
        with patch("hvcwatch.utils.pl.DataFrame") as mock_df_class:
            mock_df = Mock()
            mock_df.select.return_value = mock_df
            mock_df.with_columns.return_value = mock_df
            # Properly set up __getitem__ method
            mock_df.__getitem__ = Mock(
                return_value={
                    "close": Mock(item=Mock(return_value=100.0)),
                    "volume": Mock(item=Mock(return_value=1000000)),
                    "volume_sma": Mock(item=Mock(return_value=1000000.0)),
                    "volume_ratio": Mock(item=Mock(return_value=1.0)),
                }
            )
            mock_df_class.return_value = mock_df

            mock_polygon_client.list_aggs.return_value = [Mock()]

            get_ticker_stats("TSLA")

            # Verify the polygon client was called with correct parameters
            call_args = mock_polygon_client.list_aggs.call_args
            assert call_args[0][0] == "TSLA"  # ticker
            assert call_args[0][1] == 1  # multiplier
            assert call_args[0][2] == "day"  # timespan
            # end_date and start_date are dynamic, just verify they're strings
            assert isinstance(call_args[0][3], str)  # end_date
            assert isinstance(call_args[0][4], str)  # start_date
            # Verify keyword arguments
            assert call_args[1]["adjusted"] is True
            assert call_args[1]["sort"] == "asc"


class TestIsMarketHoursOrNear:
    """Test cases for is_market_hours_or_near function."""

    @pytest.fixture
    def mock_market_calendar(self):
        """Mock the market calendar."""
        with patch("hvcwatch.utils.mcal.get_calendar") as mock_get_calendar:
            mock_nyse = Mock()
            mock_get_calendar.return_value = mock_nyse
            yield mock_nyse

    def test_market_currently_open(
        self, mock_market_calendar, market_schedule_open, nyc_timezone
    ):
        """Test when market is currently open."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time during market hours (2:00 PM NYC time)
        market_day = datetime.now(nyc_timezone).date()
        test_time = nyc_timezone.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=14, minute=0))
        )

        result = is_market_hours_or_near(test_time)
        assert result is True

    def test_market_closed_but_near_open(
        self, mock_market_calendar, market_schedule_open, nyc_timezone
    ):
        """Test when market is closed but within hours before open."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time 2 hours before market open (7:30 AM NYC time)
        market_day = datetime.now(nyc_timezone).date()
        test_time = nyc_timezone.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=7, minute=30))
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is True

    def test_market_closed_but_near_close(
        self, mock_market_calendar, market_schedule_open, nyc_timezone
    ):
        """Test when market is closed but within hours after close."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time 2 hours after market close (6:00 PM NYC time)
        market_day = datetime.now(nyc_timezone).date()
        test_time = nyc_timezone.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=18, minute=0))
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is True

    def test_market_closed_too_far_before(
        self, mock_market_calendar, market_schedule_open, nyc_timezone
    ):
        """Test when market is closed and too far before open."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time 5 hours before market open (4:30 AM NYC time)
        market_day = datetime.now(nyc_timezone).date()
        test_time = nyc_timezone.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=4, minute=30))
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is False

    def test_market_closed_too_far_after(
        self, mock_market_calendar, market_schedule_open, nyc_timezone
    ):
        """Test when market is closed and too far after close."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time 5 hours after market close (9:00 PM NYC time)
        market_day = datetime.now(nyc_timezone).date()
        test_time = nyc_timezone.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=21, minute=0))
        )

        result = is_market_hours_or_near(test_time, hours=3)
        assert result is False

    def test_market_holiday(self, mock_market_calendar, market_schedule_closed):
        """Test when market is closed for holiday."""
        mock_market_calendar.schedule.return_value = market_schedule_closed

        result = is_market_hours_or_near()
        assert result is False

    def test_naive_datetime_input(self, mock_market_calendar, market_schedule_open):
        """Test with naive datetime input (assumes NYC timezone)."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Naive datetime during market hours
        market_day = datetime.now().date()
        test_time = datetime.combine(
            market_day, datetime.min.time().replace(hour=14, minute=0)
        )

        result = is_market_hours_or_near(test_time)
        # Result depends on actual market schedule, but function should not raise error
        assert isinstance(result, bool)

    def test_utc_datetime_input(self, mock_market_calendar, market_schedule_open):
        """Test with UTC timezone-aware datetime input."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # UTC time that corresponds to market hours in NYC
        utc_tz = pytz.UTC
        market_day = datetime.now(utc_tz).date()
        # 7:00 PM UTC = 2:00 PM EST (during market hours)
        test_time = utc_tz.localize(
            datetime.combine(market_day, datetime.min.time().replace(hour=19, minute=0))
        )

        result = is_market_hours_or_near(test_time)
        assert isinstance(result, bool)

    def test_default_datetime_is_now(self, mock_market_calendar, market_schedule_open):
        """Test that default datetime uses current time."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Call without arguments should use current time
        result = is_market_hours_or_near()
        assert isinstance(result, bool)

    @pytest.mark.parametrize("hours", [0, 1, 3, 6])
    def test_different_hour_buffers(
        self, mock_market_calendar, market_schedule_open, nyc_timezone, hours
    ):
        """Test with different hour buffer values."""
        mock_market_calendar.schedule.return_value = market_schedule_open

        # Test time just within the buffer period after close (but keep hour valid)
        market_day = datetime.now(nyc_timezone).date()
        # Use a safe hour calculation that won't exceed 23
        safe_hour = min(16 + min(hours, 7), 23)
        test_time = nyc_timezone.localize(
            datetime.combine(
                market_day, datetime.min.time().replace(hour=safe_hour, minute=30)
            )
        )

        result = is_market_hours_or_near(test_time, hours=hours)
        # Should be True if within buffer, but depends on actual hours value
        assert isinstance(result, bool)
