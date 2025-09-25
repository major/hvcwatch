from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from hvcwatch.email_monitor import (
    connect_imap,
    get_unread_messages,
    monitor_mailbox,
    process_email_message,
)


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
    "responses,expected_print",
    [
        ([{"EXISTS": 1}], True),
        ([], False),
    ],
)
def test_monitor_mailbox_detects_new_email(responses, expected_print, mock_mailbox):
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

    with patch("builtins.print") as mock_print:
        with patch("hvcwatch.email_monitor.logger"):
            try:
                monitor_mailbox(mock_mailbox)
            except KeyboardInterrupt:
                pass

        if expected_print:
            mock_print.assert_called_with(mock_msg.date, mock_msg.subject)
        else:
            mock_print.assert_not_called()


def test_connect_imap_calls_monitor_and_unread():
    mock_mailbox_instance = MagicMock()

    with (
        patch("hvcwatch.email_monitor.MailBox") as mock_mailbox_class,
        patch("hvcwatch.email_monitor.get_unread_messages") as mock_get_unread,
        patch("hvcwatch.email_monitor.monitor_mailbox") as mock_monitor,
        patch("hvcwatch.email_monitor.logger"),
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
    with (
        patch("hvcwatch.email_monitor.logger") as mock_logger,
        patch("hvcwatch.email_monitor.process_email_message") as mock_process,
    ):
        get_unread_messages(mock_mailbox)
        if unread_count == 0:
            mock_logger.info.assert_called_with("Checking for unread messages")
            mock_process.assert_not_called()
        else:
            mock_logger.info.assert_any_call(
                f"Processing {unread_count} unread messages"
            )
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
        patch("hvcwatch.email_monitor.logger") as mock_logger,
        patch(
            "hvcwatch.email_monitor.is_market_hours_or_near", return_value=market_hours
        ),
        patch("hvcwatch.email_monitor.extract_tickers", return_value=["AAPL"]),
        patch("hvcwatch.email_monitor.DiscordNotifier") as mock_notifier_cls,
    ):
        mock_notifier = MagicMock()
        mock_notifier_cls.return_value = mock_notifier
        process_email_message(msg)
        if subject is None:
            mock_logger.info.assert_any_call("Email has no subject")
            mock_notifier.notify_discord.assert_not_called()
        elif not market_hours:
            mock_logger.info.assert_any_call("Email arrived outside market hours")
            mock_notifier.notify_discord.assert_not_called()
        else:
            mock_notifier.notify_discord.assert_called_once()
