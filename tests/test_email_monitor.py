"""Tests for the email monitor.

`process_email_message` and `is_timeframe_enabled` run the real pipeline: real
ticker and timeframe parsing, market-hours check, dedup in a SQLite file under
tmp_path, real DiscordNotifier, and real company lookups. Only HTTP is faked:
Discord uses `responses` and Massive uses `httpx2_mock`, both via the shared
fixtures. The IMAP tests still patch the functions they wire together.
"""

import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses
from imap_tools.message import MailMessage

from hvcwatch.db import record_alert
from hvcwatch.email_monitor import (
    connect_imap,
    get_unread_messages,
    is_timeframe_enabled,
    monitor_mailbox,
    process_email_message,
)
from tests.helpers import SECOND_URL, WEBHOOK_URL, only_embed, posts_to

# 📅 Dates are written in Eastern time. Monday 14:30 is market hours.
MONDAY = "Mon, 02 Dec 2024 14:30:00 -0500"
FRIDAY = "Fri, 15 Nov 2024 14:30:00 -0500"
WEDNESDAY = "Wed, 20 Nov 2024 14:30:00 -0500"
SATURDAY = "Sat, 07 Dec 2024 14:30:00 -0500"  # 🌙 Market closed
# 📆 Same month as MONDAY, a year on
MONDAY_NEXT_YEAR = "Mon, 01 Dec 2025 14:30:00 -0500"

# 📧 Subjects in the format the real alert emails use
DAILY_SUBJECT = "Alert: New symbols: AAPL were added to HVC"
WEEKLY_SUBJECT = "Alert: New symbols: AAPL were added to HVC Weekly"
WEEKLY_THREE_SUBJECT = "Alert: New symbols: AAPL, MSFT, NVDA were added to HVC Weekly"
MONTHLY_SUBJECT = "Alert: New symbols: AAPL were added to HVC Monthly"


@pytest.fixture
def mock_mailbox():
    mailbox = MagicMock()
    mailbox.idle.__enter__.return_value = mailbox.idle
    mailbox.idle.__exit__.return_value = None
    mailbox.idle.poll.return_value = []
    mailbox.fetch.return_value = []
    return mailbox


def make_email(subject: str | None, date_header: str = MONDAY) -> MailMessage:
    """📨 Build a real imap_tools message. A None subject leaves the header out."""
    headers = [f"Date: {date_header}"]
    if subject is not None:
        headers.insert(0, f"Subject: {subject}")
    raw = "\r\n".join(headers) + "\r\n\r\nbody"
    return MailMessage.from_bytes(raw.encode())


def read_alert_rows(db_path: Path) -> list[tuple[str, str, str]]:
    """🗄️ Every (ticker, timeframe, alert_date) row, or [] if nothing was written."""
    if not db_path.exists():  # 🪄 sqlite3.connect would create the file, so check first
        return []
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT ticker, timeframe, alert_date FROM hvc_alerts "
            "ORDER BY ticker, timeframe, alert_date"
        ).fetchall()


def posted_titles(
    http_mock: responses.RequestsMock, url: str = WEBHOOK_URL
) -> list[str]:
    """🏷️ Embed titles of every POST sent to `url`, in order."""
    return [only_embed(payload)["title"] for payload in posts_to(http_mock, url)]


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


class TestProcessEmailMessage:
    """Real pipeline tests: parsing, market hours, dedup, delivery, and recording."""

    def test_weekly_alert_sends_and_records(
        self, http_mock, fake_discord, massive, db_path
    ):
        """📬 A new weekly ticker sends one embed with the company name and records it."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")

        # Act
        process_email_message(make_email(WEEKLY_SUBJECT))

        # Assert
        posts = posts_to(http_mock, WEBHOOK_URL)
        assert len(posts) == 1
        embed = only_embed(posts[0])
        assert embed["title"] == "AAPL"
        assert embed["description"] == (
            "**Apple Inc.**\n**Type:** CS\n**Timeframe:** Weekly"
        )
        assert read_alert_rows(db_path) == [("AAPL", "weekly", "2024-12-02")]

    def test_duplicate_weekly_email_suppressed(self, http_mock, fake_discord, db_path):
        """🔁 The same weekly email twice sends one embed and writes one row."""
        # Arrange
        fake_discord()
        msg = make_email(WEEKLY_SUBJECT)

        # Act
        process_email_message(msg)
        process_email_message(msg)

        # Assert
        assert posted_titles(http_mock) == ["AAPL"]
        assert read_alert_rows(db_path) == [("AAPL", "weekly", "2024-12-02")]

    def test_mixed_dedup_alerts_only_new_tickers(
        self, http_mock, fake_discord, db_path
    ):
        """🧩 AAPL was already sent this week, so only MSFT and NVDA alert."""
        # Arrange
        fake_discord()
        record_alert("AAPL", "weekly", date(2024, 12, 2))

        # Act
        process_email_message(make_email(WEEKLY_THREE_SUBJECT))

        # Assert
        assert posted_titles(http_mock) == ["MSFT", "NVDA"]
        assert read_alert_rows(db_path) == [
            ("AAPL", "weekly", "2024-12-02"),
            ("MSFT", "weekly", "2024-12-02"),
            ("NVDA", "weekly", "2024-12-02"),
        ]

    def test_daily_always_alerts(
        self, http_mock, fake_discord, override_settings, db_path
    ):
        """☀️ Daily alerts are never deduplicated and never recorded."""
        # Arrange
        override_settings(hvc_daily_enabled=True)  # 🔧 Daily is off by default
        fake_discord()
        msg = make_email(DAILY_SUBJECT)

        # Act
        process_email_message(msg)
        process_email_message(msg)

        # Assert
        assert posted_titles(http_mock) == ["AAPL", "AAPL"]
        assert read_alert_rows(db_path) == []

    def test_monthly_alert_uses_email_date_and_dedups_within_month(
        self, http_mock, fake_discord, db_path
    ):
        """📅 The email's Date header picks the stored month, not today's date."""
        # Arrange
        fake_discord()

        # Act: the Friday email is stored with its own date
        process_email_message(make_email(MONTHLY_SUBJECT, FRIDAY))

        # Assert
        assert read_alert_rows(db_path) == [("AAPL", "monthly", "2024-11-15")]

        # Act: a later email in the same month is suppressed
        process_email_message(make_email(MONTHLY_SUBJECT, WEDNESDAY))

        # Assert
        assert posted_titles(http_mock) == ["AAPL"]

        # Act: an email in a new month alerts again
        process_email_message(make_email(MONTHLY_SUBJECT, MONDAY))

        # Assert
        assert posted_titles(http_mock) == ["AAPL", "AAPL"]
        assert read_alert_rows(db_path) == [
            ("AAPL", "monthly", "2024-11-15"),
            ("AAPL", "monthly", "2024-12-02"),
        ]

        # Act: the same month number a year later is a new month
        process_email_message(make_email(MONTHLY_SUBJECT, MONDAY_NEXT_YEAR))

        # Assert
        assert posted_titles(http_mock) == ["AAPL", "AAPL", "AAPL"]
        assert read_alert_rows(db_path)[-1] == ("AAPL", "monthly", "2025-12-01")

    @pytest.mark.parametrize(
        ("timeframe", "subject"),
        [
            pytest.param("daily", DAILY_SUBJECT, id="daily"),
            pytest.param("weekly", WEEKLY_SUBJECT, id="weekly"),
            pytest.param("monthly", MONTHLY_SUBJECT, id="monthly"),
        ],
    )
    def test_disabled_timeframe_sends_nothing(
        self, timeframe, subject, http_mock, fake_discord, override_settings, db_path
    ):
        """🔕 A timeframe turned off in config sends nothing and records nothing."""
        # Arrange
        override_settings(**{f"hvc_{timeframe}_enabled": False})
        fake_discord()

        # Act
        process_email_message(make_email(subject))

        # Assert
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []

    def test_outside_market_hours_sends_nothing(self, http_mock, fake_discord, db_path):
        """🌙 A Saturday email is outside market hours, so nothing is sent."""
        # Arrange
        fake_discord()

        # Act
        process_email_message(make_email(WEEKLY_SUBJECT, SATURDAY))

        # Assert
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []

    @pytest.mark.parametrize(
        "subject",
        [
            pytest.param(None, id="no-subject-header"),
            pytest.param("Weekly HVC digest", id="digest-without-symbols"),
        ],
    )
    def test_email_without_tickers_sends_nothing(
        self, subject, http_mock, fake_discord, db_path
    ):
        """🔍 An email with no ticker list sends nothing and records nothing."""
        # Arrange
        fake_discord()

        # Act
        process_email_message(make_email(subject))

        # Assert
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []

    def test_failed_delivery_is_not_recorded_and_a_later_email_alerts_again(
        self, http_mock, fake_discord, db_path, caplog
    ):
        """🔁 Issue #117: a rejected POST is not recorded, so the next email retries."""
        # Arrange
        fake_discord(WEBHOOK_URL, status=400)  # 🚫 Discord rejects the first POST
        fake_discord(WEBHOOK_URL)  # ✅ The next POST succeeds
        msg = make_email(WEEKLY_SUBJECT)

        # Act
        with caplog.at_level(logging.WARNING, logger="hvcwatch.email_monitor"):
            process_email_message(msg)

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 1
        assert read_alert_rows(db_path) == []
        assert "alert not recorded" in caplog.text

        # Act
        process_email_message(msg)

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 2
        assert read_alert_rows(db_path) == [("AAPL", "weekly", "2024-12-02")]

    def test_one_working_webhook_is_enough_to_record(
        self, http_mock, fake_discord, override_settings, db_path
    ):
        """🛡️ One failing webhook does not stop the alert from being recorded."""
        # Arrange
        # 📋 The legacy WEBHOOK_URL is listed first, so it is tried before SECOND_URL
        override_settings(discord_webhook_urls=f"{SECOND_URL}, {WEBHOOK_URL}")
        fake_discord(WEBHOOK_URL, status=400)
        fake_discord(SECOND_URL)

        # Act
        process_email_message(make_email(WEEKLY_SUBJECT))

        # Assert
        assert len(posts_to(http_mock, WEBHOOK_URL)) == 1
        assert len(posts_to(http_mock, SECOND_URL)) == 1
        assert read_alert_rows(db_path) == [("AAPL", "weekly", "2024-12-02")]


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
    def test_is_timeframe_enabled(
        self, timeframe, daily, weekly, monthly, expected, override_settings
    ):
        """is_timeframe_enabled respects settings for each timeframe."""
        # Arrange
        override_settings(
            hvc_daily_enabled=daily,
            hvc_weekly_enabled=weekly,
            hvc_monthly_enabled=monthly,
        )

        # Act / Assert
        assert is_timeframe_enabled(timeframe) == expected

    def test_unknown_timeframe_is_not_enabled(self):
        """❓ A timeframe that is not daily, weekly, or monthly is not enabled."""
        assert not is_timeframe_enabled("yearly")  # ty: ignore[invalid-argument-type]
