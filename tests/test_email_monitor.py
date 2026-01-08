from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from hvcwatch.email_monitor import (
    connect_imap,
    get_unread_messages,
    is_timeframe_enabled,
    monitor_mailbox,
    process_email_message,
)


# Mock sentry_sdk for all tests in this module
@pytest.fixture(autouse=True)
def mock_sentry():
    with patch("hvcwatch.email_monitor.sentry_sdk"):
        yield


@pytest.fixture
def mock_mailbox():
    mailbox = MagicMock()
    mailbox.idle.__enter__.return_value = mailbox.idle
    mailbox.idle.__exit__.return_value = None
    mailbox.idle.poll.return_value = []
    mailbox.fetch.return_value = []
    return mailbox


@pytest.fixture
def mock_mail_message():
    msg = MagicMock()
    msg.subject = "AAPL earnings"
    msg.date = datetime(2024, 6, 1, 14, 30)
    return msg


@pytest.mark.parametrize(
    "responses,expected_process",
    [
        ([{"EXISTS": 1}], True),
        ([], False),
    ],
)
def test_monitor_mailbox_detects_new_email(responses, expected_process, mock_mailbox):
    mock_msg = MagicMock()
    mock_msg.date = datetime(2024, 6, 1, 14, 30)
    mock_msg.subject = "Test"
    mock_mailbox.fetch.return_value = [mock_msg]

    # Control the number of iterations by tracking calls
    call_count = 0

    def limited_poll(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise KeyboardInterrupt()
        return responses  # Return the actual responses for the first call

    mock_mailbox.idle.poll.side_effect = limited_poll

    with patch("hvcwatch.email_monitor.process_email_message") as mock_process:
        try:
            monitor_mailbox(mock_mailbox)
        except KeyboardInterrupt:
            pass

        if expected_process:
            mock_process.assert_called_once_with(mock_msg)
        else:
            mock_process.assert_not_called()


def test_connect_imap_calls_monitor_and_unread():
    mock_mailbox_instance = MagicMock()

    with (
        patch("hvcwatch.email_monitor.MailBox") as mock_mailbox_class,
        patch("hvcwatch.email_monitor.get_unread_messages") as mock_get_unread,
        patch("hvcwatch.email_monitor.monitor_mailbox") as mock_monitor,
    ):
        # Setup the mailbox mock to work as a context manager
        mock_mailbox_class.return_value.__enter__.return_value = mock_mailbox_instance
        mock_mailbox_class.return_value.__exit__.return_value = None
        mock_mailbox_class.return_value.login.return_value = (
            mock_mailbox_class.return_value
        )

        connect_imap("host", "user", "pass", "INBOX")

        # Verify the functions were called with the mailbox instance
        mock_get_unread.assert_called_once_with(mock_mailbox_instance)
        mock_monitor.assert_called_once_with(mock_mailbox_instance)


@pytest.mark.parametrize("unread_count", [0, 2])
def test_get_unread_messages_processes_emails(unread_count):
    mock_mailbox = MagicMock()
    mock_msgs = [
        MagicMock(subject=f"Subject {i}", date=datetime(2024, 6, 1, 14, 30))
        for i in range(unread_count)
    ]
    mock_mailbox.fetch.return_value = mock_msgs
    with patch("hvcwatch.email_monitor.process_email_message") as mock_process:
        get_unread_messages(mock_mailbox)
        if unread_count == 0:
            mock_process.assert_not_called()
        else:
            assert mock_process.call_count == unread_count


@pytest.mark.parametrize(
    "subject,date,market_hours,expected_notify",
    [
        (None, datetime(2024, 6, 1, 14, 30), True, False),
        ("AAPL earnings", datetime(2024, 6, 1, 14, 30), False, False),
        ("AAPL earnings", datetime(2024, 6, 1, 14, 30), True, True),
    ],
)
def test_process_email_message_behavior(subject, date, market_hours, expected_notify):
    msg = MagicMock()
    msg.subject = subject
    msg.date = date
    with (
        patch(
            "hvcwatch.email_monitor.is_market_hours_or_near", return_value=market_hours
        ),
        patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
        patch("hvcwatch.email_monitor.extract_timeframe", return_value="daily"),
        patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
        patch("hvcwatch.email_monitor.should_alert", return_value=True),
        patch("hvcwatch.email_monitor.record_alert"),
        patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
    ):
        process_email_message(msg)
        if expected_notify:
            mock_notify.assert_called_once_with("AAPL", "daily")
        else:
            mock_notify.assert_not_called()


class TestTimeframeEnabled:
    """Test cases for HVC timeframe enable/disable configuration."""

    @pytest.mark.parametrize(
        "timeframe,daily,weekly,monthly,expected",
        [
            ("daily", True, True, True, True),
            ("daily", False, True, True, False),
            ("weekly", True, True, True, True),
            ("weekly", True, False, True, False),
            ("monthly", True, True, True, True),
            ("monthly", True, True, False, False),
        ],
    )
    def test_is_timeframe_enabled(self, timeframe, daily, weekly, monthly, expected):
        """is_timeframe_enabled respects settings for each timeframe."""
        with patch("hvcwatch.email_monitor.settings") as mock_settings:
            mock_settings.hvc_daily_enabled = daily
            mock_settings.hvc_weekly_enabled = weekly
            mock_settings.hvc_monthly_enabled = monthly

            assert is_timeframe_enabled(timeframe) == expected

    def test_disabled_timeframe_skips_notification(self):
        """Disabled timeframe should skip notification entirely."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL were added to HVC Weekly"
        msg.date = datetime(2024, 12, 2, 14, 30)

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="weekly"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=False),
            patch("hvcwatch.email_monitor.should_alert") as mock_should,
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
        ):
            process_email_message(msg)

            # Should not even check should_alert when timeframe is disabled
            mock_should.assert_not_called()
            mock_notify.assert_not_called()
            mock_record.assert_not_called()


class TestDeduplication:
    """Test cases for HVC alert deduplication."""

    def test_weekly_alert_sends_and_records(self):
        """Weekly alerts should send notification and record to database."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL were added to HVC Weekly"
        msg.date = datetime(2024, 12, 2, 14, 30)

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="weekly"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
            patch(
                "hvcwatch.email_monitor.should_alert", return_value=True
            ) as mock_should,
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
        ):
            process_email_message(msg)

            mock_should.assert_called_once_with("AAPL", "weekly", msg.date.date())
            mock_notify.assert_called_once_with("AAPL", "weekly")
            mock_record.assert_called_once_with("AAPL", "weekly", msg.date.date())

    def test_duplicate_alert_suppressed(self):
        """Duplicate alerts should be suppressed (no notification, no record)."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL were added to HVC Weekly"
        msg.date = datetime(2024, 12, 2, 14, 30)

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="weekly"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
            patch("hvcwatch.email_monitor.should_alert", return_value=False),
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
        ):
            process_email_message(msg)

            mock_notify.assert_not_called()
            mock_record.assert_not_called()

    def test_multiple_tickers_mixed_dedup(self):
        """Multiple tickers: some may alert, others suppressed."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL, MSFT, NVDA were added to HVC Weekly"
        msg.date = datetime(2024, 12, 2, 14, 30)

        # AAPL is duplicate, MSFT and NVDA are new
        should_alert_returns = [False, True, True]

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch(
                "hvcwatch.email_monitor.extract_tickers",
                return_value=["AAPL", "MSFT", "NVDA"],
            ),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="weekly"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
            patch(
                "hvcwatch.email_monitor.should_alert", side_effect=should_alert_returns
            ),
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
        ):
            process_email_message(msg)

            # Only MSFT and NVDA should send
            assert mock_notify.call_count == 2
            mock_notify.assert_any_call("MSFT", "weekly")
            mock_notify.assert_any_call("NVDA", "weekly")

            # Only MSFT and NVDA should be recorded
            assert mock_record.call_count == 2

    def test_daily_always_alerts(self):
        """Daily timeframe should always alert (no deduplication)."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL were added to HVC"
        msg.date = datetime(2024, 12, 2, 14, 30)

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="daily"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
            patch(
                "hvcwatch.email_monitor.should_alert", return_value=True
            ) as mock_should,
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms") as mock_notify,
        ):
            process_email_message(msg)

            mock_should.assert_called_once_with("AAPL", "daily", msg.date.date())
            mock_notify.assert_called_once_with("AAPL", "daily")
            mock_record.assert_called_once()

    def test_uses_email_date_for_alert_date(self):
        """Should use email date (not today) for deduplication checks."""
        msg = MagicMock()
        msg.subject = "Alert: New symbols: AAPL were added to HVC Monthly"
        msg.date = datetime(2024, 11, 15, 14, 30)  # Date in the past

        with (
            patch("hvcwatch.email_monitor.is_market_hours_or_near", return_value=True),
            patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
            patch("hvcwatch.email_monitor.extract_timeframe", return_value="monthly"),
            patch("hvcwatch.email_monitor.is_timeframe_enabled", return_value=True),
            patch(
                "hvcwatch.email_monitor.should_alert", return_value=True
            ) as mock_should,
            patch("hvcwatch.email_monitor.record_alert") as mock_record,
            patch("hvcwatch.email_monitor.notify_all_platforms"),
        ):
            process_email_message(msg)

            # Should use the email's date, not today
            expected_date = msg.date.date()
            mock_should.assert_called_once_with("AAPL", "monthly", expected_date)
            mock_record.assert_called_once_with("AAPL", "monthly", expected_date)
