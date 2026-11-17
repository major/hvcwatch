"""Tests for the email monitor.

Every test runs the real pipeline: real IMAP-to-alert flow, ticker and timeframe
parsing, market-hours check, dedup in a SQLite file under tmp_path, real
DiscordNotifier, and real company lookups. Only two boundaries are faked: HTTP
(Discord uses `responses`, Massive uses `httpx2_mock`, both via the shared
fixtures) and the imap_tools MailBox (`fake_mailbox`, a scripted FakeMailBox
from conftest.py).
"""

import logging
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
import responses
from imap_tools.message import MailMessage

from hvcwatch.db import get_cursor, record_alert, save_cursor
from hvcwatch.email_monitor import (
    connect_imap,
    fetch_new_messages,
    is_timeframe_enabled,
    monitor_mailbox,
    process_email_message,
)
from tests.helpers import SECOND_URL, WEBHOOK_URL, ScriptExhausted, only_embed, posts_to

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
MSFT_WEEKLY_SUBJECT = "Alert: New symbols: MSFT were added to HVC Weekly"
WEEKLY_THREE_SUBJECT = "Alert: New symbols: AAPL, MSFT, NVDA were added to HVC Weekly"
MONTHLY_SUBJECT = "Alert: New symbols: AAPL were added to HVC Monthly"

# 📨 What IDLE returns when the server reports a new message
NEW_MAIL = [b"* 1 EXISTS"]

# 📁 The folder name and UIDVALIDITY that the fake mailbox and saved cursors use
FOLDER = "Alerts"
UIDVALIDITY = 1  # 🆔 Matches the fake mailbox default


def make_email(
    subject: str | None, date_header: str = MONDAY, uid: int = 1
) -> MailMessage:
    """📨 Build a real imap_tools message with a UID. A None subject leaves the header out."""
    headers = [f"Date: {date_header}"]
    if subject is not None:
        headers.insert(0, f"Subject: {subject}")
    raw = "\r\n".join(headers) + "\r\n\r\nbody"
    # 🧾 The UID comes from the FETCH response, as imap_tools reads it from the server
    fetch_item = (f"1 (UID {uid} FLAGS ())".encode(), raw.encode())
    return MailMessage([fetch_item])


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


class TestFetchNewMessages:
    """Mail after the saved UID cursor is processed once, read-only, and the cursor follows it."""

    def test_first_run_baselines_at_uidnext_minus_one_and_sends_nothing(
        self, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """🌱 With no saved cursor, old mail is skipped: the cursor goes to UIDNEXT - 1 and no body is fetched."""
        # Arrange
        fake_discord()
        mailbox = fake_mailbox(uidvalidity=UIDVALIDITY, uidnext=42)

        # Act
        fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert get_cursor(FOLDER) == (UIDVALIDITY, 41)
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []
        assert mailbox.fetch_calls == []

    def test_uidvalidity_change_resets_cursor_and_warns(
        self, http_mock, fake_discord, fake_mailbox, caplog
    ):
        """♻️ A new UIDVALIDITY makes the old UIDs meaningless: the cursor restarts with a warning."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, 7, 30)
        mailbox = fake_mailbox(uidvalidity=8, uidnext=5)

        # Act
        with caplog.at_level(logging.WARNING, logger="hvcwatch.email_monitor"):
            fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert get_cursor(FOLDER) == (8, 4)
        assert posted_titles(http_mock) == []
        assert mailbox.fetch_calls == []
        assert "UIDVALIDITY changed" in caplog.text
        assert "old=7" in caplog.text
        assert "new=8" in caplog.text

    def test_new_mail_after_cursor_is_processed_in_order_and_cursor_advances(
        self, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """📬 Mail after the cursor goes through the pipeline in UID order, fetched without setting \\Seen."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, UIDVALIDITY, 10)
        mailbox = fake_mailbox(
            fetches=[
                [
                    make_email(WEEKLY_SUBJECT, uid=11),
                    make_email(MSFT_WEEKLY_SUBJECT, uid=12),
                ]
            ],
            uidvalidity=UIDVALIDITY,
            uidnext=13,
        )

        # Act
        fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert posted_titles(http_mock) == ["AAPL", "MSFT"]
        assert read_alert_rows(db_path) == [
            ("AAPL", "weekly", "2024-12-02"),
            ("MSFT", "weekly", "2024-12-02"),
        ]
        assert mailbox.fetch_calls == [
            ("(UID 11:*)", False)
        ]  # 🔒 Read-only: BODY.PEEK, no \Seen
        assert get_cursor(FOLDER) == (UIDVALIDITY, 12)

    @pytest.mark.parametrize(
        "stale_uid",
        [pytest.param(10, id="same-uid"), pytest.param(3, id="older-uid")],
    )
    def test_message_at_or_below_cursor_is_skipped(
        self, stale_uid, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """🪤 IMAP's N:* returns the newest mail even when it is older than N, so such mail is skipped."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, UIDVALIDITY, 10)
        mailbox = fake_mailbox(
            fetches=[[make_email(WEEKLY_SUBJECT, uid=stale_uid)]],
            uidvalidity=UIDVALIDITY,
            uidnext=11,
        )

        # Act
        fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []
        assert get_cursor(FOLDER) == (UIDVALIDITY, 10)

    def test_no_new_mail_leaves_cursor_unchanged(self, fake_mailbox):
        """📭 An empty result after the cursor keeps the saved position."""
        # Arrange
        save_cursor(FOLDER, UIDVALIDITY, 10)
        mailbox = fake_mailbox(fetches=[[]], uidvalidity=UIDVALIDITY, uidnext=11)

        # Act
        fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert mailbox.fetch_calls == [("(UID 11:*)", False)]
        assert get_cursor(FOLDER) == (UIDVALIDITY, 10)

    def test_failed_message_keeps_cursor_on_last_good_one_and_propagates(
        self, monkeypatch, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """🛑 If processing raises, the cursor stops before that message and later mail waits for the next run."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, UIDVALIDITY, 10)
        attempted: list[str | None] = []

        def fail_on_second(msg: MailMessage) -> None:
            """💥 Real processing for the first message, an error for the second."""
            attempted.append(msg.uid)
            if msg.uid == "12":
                raise RuntimeError("delivery pipeline broke")
            process_email_message(msg)

        monkeypatch.setattr(
            "hvcwatch.email_monitor.process_email_message", fail_on_second
        )
        mailbox = fake_mailbox(
            fetches=[
                [
                    make_email(WEEKLY_SUBJECT, uid=11),
                    make_email(MSFT_WEEKLY_SUBJECT, uid=12),
                    make_email(WEEKLY_THREE_SUBJECT, uid=13),
                ]
            ],
            uidvalidity=UIDVALIDITY,
            uidnext=14,
        )

        # Act
        with pytest.raises(RuntimeError, match="delivery pipeline broke"):
            fetch_new_messages(mailbox, FOLDER)

        # Assert
        assert attempted == ["11", "12"]  # ⏭️ The third message is never reached
        assert posted_titles(http_mock) == ["AAPL"]
        assert get_cursor(FOLDER) == (UIDVALIDITY, 11)


class TestMonitorMailbox:
    """The IDLE loop: a poll that reports new mail fetches and processes mail after the cursor."""

    def test_new_mail_during_idle_is_fetched_and_processed(
        self, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """📨 A new-mail poll fetches the weekly alert after the cursor, then the loop polls again."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, UIDVALIDITY, 10)
        mailbox = fake_mailbox(
            fetches=[[make_email(WEEKLY_SUBJECT, uid=11)]],
            polls=[NEW_MAIL],
            uidvalidity=UIDVALIDITY,
            uidnext=12,
        )

        # Act: the script ends on the second poll
        with pytest.raises(ScriptExhausted):
            monitor_mailbox(mailbox, FOLDER)

        # Assert
        assert posted_titles(http_mock) == ["AAPL"]
        assert read_alert_rows(db_path) == [("AAPL", "weekly", "2024-12-02")]
        assert mailbox.fetch_calls == [("(UID 11:*)", False)]
        assert mailbox.idle.timeouts == [10, 10]

    def test_idle_timeout_without_new_mail_fetches_nothing(
        self, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """⏱️ An IDLE timeout with no new mail neither fetches nor sends anything."""
        # Arrange
        fake_discord()
        mailbox = fake_mailbox(polls=[[]])

        # Act: the script ends on the second poll
        with pytest.raises(ScriptExhausted):
            monitor_mailbox(mailbox, FOLDER)

        # Assert
        assert posted_titles(http_mock) == []
        assert read_alert_rows(db_path) == []
        assert mailbox.fetch_calls == []
        assert mailbox.idle.timeouts == [10, 10]


class TestConnectImap:
    """connect_imap opens the folder read-only, resumes the backlog, then monitors IDLE."""

    def test_opens_read_only_resumes_backlog_then_idle_mail_and_logs_out(
        self, http_mock, fake_discord, fake_mailbox, db_path
    ):
        """🔌 Login skips the default SELECT, EXAMINEs the folder, sends backlog AAPL, then IDLE MSFT, then logs out."""
        # Arrange
        fake_discord()
        save_cursor(FOLDER, UIDVALIDITY, 10)
        mailbox = fake_mailbox(
            fetches=[
                [make_email(WEEKLY_SUBJECT, uid=11)],
                [make_email(MSFT_WEEKLY_SUBJECT, uid=12)],
            ],
            polls=[NEW_MAIL],
            uidvalidity=UIDVALIDITY,
            uidnext=13,
        )

        # Act: the script ends on the second IDLE poll
        with pytest.raises(ScriptExhausted):
            connect_imap("imap.example.com", "user", "pass", FOLDER)

        # Assert
        assert mailbox.host == "imap.example.com"
        assert mailbox.login_args == ("user", "pass", None)  # 🔌 No default SELECT
        assert mailbox.folder.selected == (FOLDER, True)  # 🔒 EXAMINE, never SELECT
        assert posted_titles(http_mock) == ["AAPL", "MSFT"]
        assert read_alert_rows(db_path) == [
            ("AAPL", "weekly", "2024-12-02"),
            ("MSFT", "weekly", "2024-12-02"),
        ]
        assert mailbox.fetch_calls == [("(UID 11:*)", False), ("(UID 12:*)", False)]
        assert mailbox.logged_out


class TestProcessEmailMessage:
    """Real pipeline tests: parsing, market hours, dedup, delivery, and recording."""

    def test_weekly_alert_sends_and_records(
        self, http_mock, fake_discord, massive, db_path
    ):
        """📬 A new weekly ticker sends one embed titled with the company name and records it."""
        # Arrange
        fake_discord()
        massive("AAPL", "Apple Inc.", "CS")

        # Act
        process_email_message(make_email(WEEKLY_SUBJECT))

        # Assert
        posts = posts_to(http_mock, WEBHOOK_URL)
        assert len(posts) == 1
        embed = only_embed(posts[0])
        assert embed["title"] == "Apple Inc."
        assert embed["description"] == "**AAPL** · CS · Weekly"
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

    def test_daily_always_alerts(self, http_mock, fake_discord, db_path):
        """☀️ Daily alerts are never deduplicated and never recorded."""
        # Arrange
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
