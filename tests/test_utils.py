from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from hvcwatch.utils import (
    _get_nyse_calendar,
    extract_tickers,
    extract_timeframe,
    get_company_name,
    get_ticker_type,
    is_market_hours_or_near,
)

# 🗽 Real New York wall-clock zone. The market tests use the real XNYS calendar.
NYC = ZoneInfo("America/New_York")


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
    """Test cases for is_market_hours_or_near function.

    These tests use the real XNYS calendar on fixed 2026 dates, so results do not
    depend on today's date or on a mocked calendar.
    """

    @pytest.mark.parametrize(
        "day,expected",
        [
            pytest.param(date(2026, 1, 6), True, id="normal-tuesday"),
            pytest.param(date(2026, 3, 9), True, id="day-after-dst-start"),
            pytest.param(date(2026, 11, 2), True, id="day-after-dst-end"),
            pytest.param(date(2026, 11, 27), True, id="early-close-friday"),
            pytest.param(date(2026, 1, 10), False, id="weekend"),
            pytest.param(date(2026, 1, 19), False, id="mlk-day"),
            pytest.param(date(2026, 12, 25), False, id="christmas"),
        ],
    )
    def test_fixed_dates_match_the_xnys_calendar(self, day, expected):
        """Guard the fixed 2026 dates so a wrong date fails here, not as a boundary failure."""
        assert _get_nyse_calendar().is_session(day) == expected

    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            pytest.param(
                datetime(2026, 1, 6, 9, 29, 59, 999999, tzinfo=NYC),
                0,
                False,
                id="one-microsecond-before-open",
            ),
            pytest.param(
                datetime(2026, 1, 6, 9, 30, tzinfo=NYC), 0, True, id="open-instant"
            ),
            pytest.param(datetime(2026, 1, 6, 14, 0, tzinfo=NYC), 0, True, id="midday"),
            pytest.param(
                datetime(2026, 1, 6, 16, 0, tzinfo=NYC), 0, True, id="close-instant"
            ),
            pytest.param(
                datetime(2026, 1, 6, 16, 0, 0, 1, tzinfo=NYC),
                0,
                False,
                id="one-microsecond-after-close",
            ),
        ],
    )
    def test_regular_session_boundaries(self, check_time, hours, expected):
        """Open and close instants are inside the session. One microsecond outside is not."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            pytest.param(
                datetime(2026, 1, 6, 8, 30, tzinfo=NYC),
                1,
                True,
                id="exactly-one-hour-before-open",
            ),
            pytest.param(
                datetime(2026, 1, 6, 8, 29, 59, tzinfo=NYC),
                1,
                False,
                id="one-second-before-pre-window",
            ),
            pytest.param(
                datetime(2026, 1, 6, 17, 0, tzinfo=NYC),
                1,
                True,
                id="exactly-one-hour-after-close",
            ),
            pytest.param(
                datetime(2026, 1, 6, 17, 0, 1, tzinfo=NYC),
                1,
                False,
                id="one-second-after-post-window",
            ),
            pytest.param(
                datetime(2026, 1, 6, 7, 30, tzinfo=NYC),
                3,
                True,
                id="two-hours-before-open-with-3h-buffer",
            ),
            pytest.param(
                datetime(2026, 1, 6, 18, 0, tzinfo=NYC),
                3,
                True,
                id="two-hours-after-close-with-3h-buffer",
            ),
            pytest.param(
                datetime(2026, 1, 6, 4, 30, tzinfo=NYC),
                3,
                False,
                id="five-hours-before-open-with-3h-buffer",
            ),
            pytest.param(
                datetime(2026, 1, 6, 21, 0, tzinfo=NYC),
                3,
                False,
                id="five-hours-after-close-with-3h-buffer",
            ),
        ],
    )
    def test_near_open_and_close_buffers(self, check_time, hours, expected):
        """The pre-open and post-close windows include their edges and nothing beyond."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            pytest.param(
                datetime(2026, 1, 6, 16, 30, tzinfo=NYC), 0, False, id="no-buffer"
            ),
            pytest.param(
                datetime(2026, 1, 6, 16, 30, tzinfo=NYC), 1, True, id="one-hour-buffer"
            ),
            pytest.param(
                datetime(2026, 1, 6, 16, 30, tzinfo=NYC),
                3,
                True,
                id="three-hour-buffer",
            ),
            pytest.param(
                datetime(2026, 1, 6, 16, 30, tzinfo=NYC), 6, True, id="six-hour-buffer"
            ),
            pytest.param(
                datetime(2026, 1, 6, 22, 30, tzinfo=NYC),
                6,
                False,
                id="past-six-hour-buffer",
            ),
        ],
    )
    def test_hour_buffers_after_close(self, check_time, hours, expected):
        """The post-close buffer grows with hours. Close is 16:00, so 6h ends at 22:00."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time,expected",
        [
            pytest.param(
                datetime(2026, 1, 6, 8, 45, tzinfo=NYC), True, id="within-default-hour"
            ),
            pytest.param(
                datetime(2026, 1, 6, 8, 15, tzinfo=NYC),
                False,
                id="beyond-default-hour",
            ),
        ],
    )
    def test_default_hours_is_one_hour(self, check_time, expected):
        """Omitting hours uses a one-hour buffer."""
        result = is_market_hours_or_near(check_time)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            # 🕗 Naive input is New York wall-clock time, so 20:00 is after close.
            pytest.param(
                datetime(2026, 1, 6, 14, 0), 0, True, id="naive-is-new-york-midday"
            ),
            pytest.param(
                datetime(2026, 1, 6, 20, 0),
                0,
                False,
                id="naive-20-00-is-not-utc",
            ),
            # 🌍 UTC input is converted to New York first.
            pytest.param(
                datetime(2026, 1, 6, 19, 0, tzinfo=UTC),
                0,
                True,
                id="utc-1900-is-1400-new-york",
            ),
            pytest.param(
                datetime(2026, 1, 6, 14, 29, 59, tzinfo=UTC),
                0,
                False,
                id="utc-one-second-before-open",
            ),
            pytest.param(
                datetime(2026, 1, 6, 14, 30, tzinfo=UTC),
                0,
                True,
                id="utc-open-instant",
            ),
            pytest.param(
                datetime(2026, 1, 6, 22, 0, tzinfo=UTC),
                0,
                False,
                id="utc-2200-is-1700-new-york",
            ),
        ],
    )
    def test_naive_and_utc_inputs_are_normalized(self, check_time, hours, expected):
        """Naive input is New York time. Aware input is converted to New York."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time",
        [
            pytest.param(datetime(2026, 1, 10, 12, 0, tzinfo=NYC), id="weekend-noon"),
            pytest.param(datetime(2026, 1, 10, 9, 0, tzinfo=NYC), id="weekend-0900"),
            pytest.param(datetime(2026, 1, 19, 12, 0, tzinfo=NYC), id="mlk-day-noon"),
            pytest.param(datetime(2026, 1, 19, 9, 0, tzinfo=NYC), id="mlk-day-0900"),
            pytest.param(
                datetime(2026, 12, 25, 12, 0, tzinfo=NYC), id="christmas-noon"
            ),
            pytest.param(datetime(2026, 12, 25, 9, 0, tzinfo=NYC), id="christmas-0900"),
        ],
    )
    def test_closed_days_are_never_near_the_window(self, check_time):
        """A closed day has no window, even with a 3-hour buffer."""
        result = is_market_hours_or_near(check_time, hours=3)

        assert result is False

    # 🌗 Mar 9 and Nov 2 are the days after the DST changes. EDT is UTC-4, EST is UTC-5.
    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            pytest.param(
                datetime(2026, 3, 9, 13, 29, 59, tzinfo=UTC),
                0,
                False,
                id="mar-9-one-second-before-open",
            ),
            pytest.param(
                datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
                0,
                True,
                id="mar-9-open-edt",
            ),
            pytest.param(
                datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
                0,
                True,
                id="mar-9-close-edt",
            ),
            pytest.param(
                datetime(2026, 3, 9, 20, 0, 0, 1, tzinfo=UTC),
                0,
                False,
                id="mar-9-one-microsecond-after-close",
            ),
            # 🕛 00:30 EDT on Mar 9 is 23:30 EST on Mar 8, a closed Sunday in fixed UTC-5.
            pytest.param(
                datetime(2026, 3, 9, 4, 30, tzinfo=UTC),
                9,
                True,
                id="mar-9-pre-window-reaches-0030-edt",
            ),
            pytest.param(
                datetime(2026, 11, 2, 14, 29, 59, tzinfo=UTC),
                0,
                False,
                id="nov-2-one-second-before-open",
            ),
            pytest.param(
                datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
                0,
                True,
                id="nov-2-open-est",
            ),
            pytest.param(
                datetime(2026, 11, 2, 21, 0, tzinfo=UTC),
                0,
                True,
                id="nov-2-close-est",
            ),
            pytest.param(
                datetime(2026, 11, 2, 21, 0, 0, 1, tzinfo=UTC),
                0,
                False,
                id="nov-2-one-microsecond-after-close",
            ),
        ],
    )
    def test_dst_transitions_use_real_offsets(self, check_time, hours, expected):
        """Open and close follow the real offset on each side of the DST change."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    @pytest.mark.parametrize(
        "check_time,hours,expected",
        [
            pytest.param(
                datetime(2026, 11, 27, 13, 0, tzinfo=NYC), 0, True, id="close-1300"
            ),
            pytest.param(
                datetime(2026, 11, 27, 13, 0, 0, 1, tzinfo=NYC),
                0,
                False,
                id="one-microsecond-after-1300",
            ),
            pytest.param(
                datetime(2026, 11, 27, 14, 0, tzinfo=NYC),
                1,
                True,
                id="one-hour-after-early-close",
            ),
            pytest.param(
                datetime(2026, 11, 27, 15, 0, tzinfo=NYC),
                1,
                False,
                id="regular-close-would-say-true",
            ),
        ],
    )
    def test_early_close_shortens_the_session(self, check_time, hours, expected):
        """Nov 27 closes at 13:00, so the post-close window ends at 14:00 with 1h."""
        result = is_market_hours_or_near(check_time, hours=hours)

        assert result is expected

    def test_check_time_is_required(self):
        """check_time has no default, so there is no stale import-time clock read."""
        with pytest.raises(TypeError):
            is_market_hours_or_near()  # ty: ignore[missing-argument]

    @pytest.mark.parametrize(
        "out_of_range",
        [
            datetime(1900, 1, 1),  # 📭 imap_tools value for a missing or bad Date
            datetime(2100, 1, 1),  # 🔮 past the last session of the calendar
        ],
    )
    def test_out_of_range_date_warns_and_returns_false(self, out_of_range, caplog):
        """Dates outside the XNYS calendar log a warning and return False."""
        with caplog.at_level("WARNING", logger="hvcwatch.utils"):
            result = is_market_hours_or_near(out_of_range)

        assert result is False
        assert "outside the NYSE calendar range" in caplog.text


OK_BODY = b'{"status":"OK","results":{"name":"Apple Inc.","ticker":"AAPL"}}'
OK_BODY_WITH_TYPE = (
    b'{"status":"OK","results":{"name":"Apple Inc.","ticker":"AAPL","type":"CS"}}'
)
MASSIVE_AAPL_URL = "https://api.massive.com/v3/reference/tickers/AAPL"
MASSIVE_ZZZZ_URL = "https://api.massive.com/v3/reference/tickers/ZZZZ"


def warning_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """📜 Messages logged at WARNING level during the test."""
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


@pytest.fixture
def api_key(override_settings):
    """🔑 Configure a fake Massive API key."""
    override_settings(massive_api_key="test-key")


class TestGetCompanyName:
    """Test cases for get_company_name using the live Massive API."""

    def test_returns_name_from_massive(self, api_key, http_mock):
        """✅ A 200 response returns results.name."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        name = get_company_name("AAPL")

        # Assert
        assert name == "Apple Inc."

    def test_ticker_is_uppercased_and_bearer_header_sent(self, api_key, http_mock):
        """✅ The URL uses an uppercase ticker and the key goes in the header, not the URL."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        get_company_name("aapl")

        # Assert
        assert len(http_mock.calls) == 1
        request = http_mock.calls[0].request
        assert request.url == MASSIVE_AAPL_URL
        assert request.headers["Authorization"] == "Bearer test-key"
        assert "test-key" not in request.url
        assert request.req_kwargs["timeout"] == 10

    def test_unknown_ticker_404_returns_none_and_is_cached(
        self, api_key, http_mock, caplog
    ):
        """✅ A 404 returns None and is cached, so the second call sends no request."""
        # Arrange
        http_mock.get(MASSIVE_ZZZZ_URL, status=404)

        # Act
        with caplog.at_level("INFO", logger="hvcwatch.utils"):
            first = get_company_name("ZZZZ")
            second = get_company_name("ZZZZ")

        # Assert
        assert (first, second) == (None, None)
        assert len(http_mock.calls) == 1
        assert "Ticker not found on Massive ticker=ZZZZ" in caplog.messages

    @pytest.mark.parametrize("status_code", [401, 403, 500, 429])
    def test_http_error_returns_none_and_is_not_cached(
        self, api_key, http_mock, status_code
    ):
        """✅ A 401, 403, 5xx, or 429 returns None, and the next call retries the API."""
        # Arrange: first reply is an error, second reply succeeds
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY, status=status_code)
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        first = get_company_name("AAPL")
        second = get_company_name("AAPL")

        # Assert
        assert first is None
        assert second == "Apple Inc."
        assert len(http_mock.calls) == 2

    @pytest.mark.parametrize(
        "error",
        [requests.Timeout("timed out"), requests.ConnectionError("no route")],
    )
    def test_network_errors_return_none(self, api_key, http_mock, error):
        """✅ Timeouts and connection errors never raise to the caller."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=error)

        # Act
        name = get_company_name("AAPL")

        # Assert
        assert name is None

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b'{"status":"OK","results":{"ticker":"AAPL"}}',
            b'{"status":"OK"}',
        ],
        ids=["bad-json", "missing-name", "missing-results"],
    )
    def test_malformed_payload_returns_none_and_is_not_cached(
        self, api_key, http_mock, body
    ):
        """✅ Bad JSON, or a missing results.name or results, returns None and is retried."""
        # Arrange: first reply is malformed, second reply is valid
        http_mock.get(MASSIVE_AAPL_URL, body=body)
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        first = get_company_name("AAPL")
        second = get_company_name("AAPL")

        # Assert
        assert first is None
        assert second == "Apple Inc."
        assert len(http_mock.calls) == 2

    def test_missing_api_key_skips_http_call(self, http_mock, caplog):
        """✅ Without a key, no HTTP call is made, the result is None, and a warning is logged."""
        # Act
        with caplog.at_level("INFO", logger="hvcwatch.utils"):
            name = get_company_name("AAPL")

        # Assert
        assert name is None
        assert len(http_mock.calls) == 0
        assert (
            "Massive API key not set, skipping company name lookup"
            in warning_messages(caplog)
        )

    def test_successful_lookup_is_cached(self, api_key, http_mock):
        """✅ A successful lookup costs one HTTP call, even for a different case."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        first = get_company_name("AAPL")
        second = get_company_name("aapl")

        # Assert
        assert (first, second) == ("Apple Inc.", "Apple Inc.")
        assert len(http_mock.calls) == 1


class TestGetTickerType:
    """Test cases for get_ticker_type, which shares one overview call with get_company_name."""

    @pytest.mark.parametrize("code", ["CS", "ETF", "ADRC"])
    def test_returns_type_code(self, api_key, http_mock, code):
        """✅ A 200 response returns results.type as Massive sends it."""
        # Arrange
        http_mock.get(
            MASSIVE_AAPL_URL,
            json={"status": "OK", "results": {"name": "Apple Inc.", "type": code}},
        )

        # Act
        ticker_type = get_ticker_type("AAPL")

        # Assert
        assert ticker_type == code

    def test_name_and_type_share_one_http_call(self, api_key, http_mock):
        """✅ Name and type for one ticker cost one HTTP call, and both come from it."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY_WITH_TYPE)

        # Act
        name = get_company_name("AAPL")
        ticker_type = get_ticker_type("aapl")

        # Assert
        assert (name, ticker_type) == ("Apple Inc.", "CS")
        assert len(http_mock.calls) == 1

    def test_missing_api_key_skips_http_call(self, http_mock, caplog):
        """✅ Without a key, no HTTP call is made, the type is None, and a warning is logged."""
        # Act
        with caplog.at_level("INFO", logger="hvcwatch.utils"):
            ticker_type = get_ticker_type("AAPL")

        # Assert
        assert ticker_type is None
        assert len(http_mock.calls) == 0
        assert (
            "Massive API key not set, skipping ticker type lookup"
            in warning_messages(caplog)
        )

    def test_missing_type_keeps_company_name(self, api_key, http_mock):
        """✅ A 200 response without results.type has no type but still returns the name."""
        # Arrange
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY)

        # Act
        name = get_company_name("AAPL")
        ticker_type = get_ticker_type("AAPL")

        # Assert
        assert name == "Apple Inc."
        assert ticker_type is None

    def test_unknown_ticker_404_is_none_for_both_and_cached(self, api_key, http_mock):
        """✅ A 404 gives None for name and type, and the empty result is cached."""
        # Arrange
        http_mock.get(MASSIVE_ZZZZ_URL, status=404)

        # Act
        name = get_company_name("ZZZZ")
        ticker_type = get_ticker_type("ZZZZ")

        # Assert
        assert (name, ticker_type) == (None, None)
        assert len(http_mock.calls) == 1

    def test_transient_failures_are_none_for_both_and_not_cached(
        self, api_key, http_mock
    ):
        """✅ A 500 and a timeout each return None, and the next call retries the API."""
        # Arrange: 500, then timeout, then success
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY, status=500)
        http_mock.get(MASSIVE_AAPL_URL, body=requests.Timeout("timed out"))
        http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY_WITH_TYPE)

        # Act
        first_name = get_company_name("AAPL")
        first_type = get_ticker_type("AAPL")
        second_name = get_company_name("AAPL")
        second_type = get_ticker_type("AAPL")

        # Assert
        assert (first_name, first_type) == (None, None)
        assert (second_name, second_type) == ("Apple Inc.", "CS")
        assert len(http_mock.calls) == 3


@pytest.mark.parametrize(
    "lookup, label",
    [(get_company_name, "Company name"), (get_ticker_type, "Ticker type")],
    ids=["company-name", "ticker-type"],
)
def test_server_error_logs_warning_without_leaking_key(
    override_settings, http_mock, caplog, lookup, label
):
    """📜 A 500 logs a warning for the lookup, and the API key never reaches the log."""
    # Arrange
    override_settings(massive_api_key="test-key")
    http_mock.get(MASSIVE_AAPL_URL, body=OK_BODY, status=500)

    # Act
    with caplog.at_level("INFO", logger="hvcwatch.utils"):
        result = lookup("AAPL")

    # Assert
    assert result is None
    assert any(
        message.startswith(f"{label} lookup failed ticker=AAPL")
        for message in warning_messages(caplog)
    )
    assert "test-key" not in caplog.text
