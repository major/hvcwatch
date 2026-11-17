import logging
from datetime import date

from imap_tools.mailbox import BaseMailBox, MailBox
from imap_tools.message import MailMessage
from imap_tools.query import A

from hvcwatch import config
from hvcwatch.db import get_cursor, record_alert, save_cursor, should_alert
from hvcwatch.notification import Timeframe, notify_all_platforms
from hvcwatch.utils import extract_tickers, extract_timeframe, is_market_hours_or_near

logger = logging.getLogger(__name__)


def is_timeframe_enabled(timeframe: Timeframe) -> bool:
    """
    Check if a given HVC timeframe is enabled in configuration.

    Args:
        timeframe: The alert timeframe to check ("daily", "weekly", or "monthly")

    Returns:
        True if the timeframe is enabled, False otherwise
    """
    settings = config.get_settings()
    match timeframe:
        case "daily":
            return settings.hvc_daily_enabled
        case "weekly":
            return settings.hvc_weekly_enabled
        case "monthly":
            return settings.hvc_monthly_enabled


def connect_imap(host: str, user: str, password: str, folder: str) -> None:
    """
    Connects to an IMAP mailbox read-only and monitors the folder for new emails.

    The folder is opened with EXAMINE, never SELECT, so the server is never
    written to: no flags are set and no mail is moved. 🔒

    Args:
        host (str): The IMAP server hostname.
        user (str): The username for authentication.
        password (str): The password for authentication.
        folder (str): The mailbox folder to monitor.

    Raises:
        KeyboardInterrupt: If monitoring is interrupted by the user.

    Side Effects:
        Logs monitoring start and stop events.
        Calls fetch_new_messages for the backlog and monitor_mailbox for new mail.
    """
    # 🔒 initial_folder=None skips the default SELECT, so only the EXAMINE below opens the folder
    with MailBox(host).login(user, password, initial_folder=None) as mailbox:
        mailbox.folder.set(folder, readonly=True)
        fetch_new_messages(mailbox, folder)

        try:
            logger.info("Starting email monitoring")
            monitor_mailbox(mailbox, folder)
        except KeyboardInterrupt:  # pragma: no cover
            logger.info("Stopping email monitoring")


def monitor_mailbox(mailbox: BaseMailBox, folder: str) -> None:
    """
    Monitors the given folder for new emails using the IDLE protocol.

    Waits in IDLE for up to 10 seconds at a time. When the server reports new
    mail, logs the event and processes everything after the saved cursor.

    Args:
        mailbox (BaseMailBox): The open, read-only mailbox session to monitor.
        folder (str): The folder to monitor, passed on to fetch_new_messages.
    """
    while True:
        with mailbox.idle as idle:
            responses = idle.poll(timeout=10)

        if responses:
            logger.info("New email detected while IDLE")
            fetch_new_messages(mailbox, folder)


def fetch_new_messages(mailbox: BaseMailBox, folder: str) -> None:
    """
    Processes the emails in a folder that arrived after the saved UID cursor.

    The cursor is a (UIDVALIDITY, last UID) pair kept in the local SQLite
    database. Reading mail with BODY.PEEK leaves the server untouched, so no
    \\Seen flags change. 🔒

    UIDs are only unique within one UIDVALIDITY. On a first run, or when
    UIDVALIDITY changes (the server renumbered the folder), the cursor moves to
    UIDNEXT - 1 and nothing is processed. This keeps old mail from sending alerts. 🌱

    Args:
        mailbox (BaseMailBox): The open, read-only mailbox session.
        folder (str): The folder name, used as the key for the saved cursor.

    Logs:
        - Info on a first run.
        - Warning when UIDVALIDITY changed, with the old and new values.
        - Info with the subject and date of each new email processed.
    """
    status = mailbox.folder.status(folder, ["UIDVALIDITY", "UIDNEXT"])
    uidvalidity = status["UIDVALIDITY"]
    cursor = get_cursor(folder)

    if cursor is None or cursor[0] != uidvalidity:
        if cursor is None:
            logger.info("First run, skipping existing mail folder=%s", folder)
        else:
            logger.warning(
                "UIDVALIDITY changed, skipping existing mail folder=%s old=%s new=%s",
                folder,
                cursor[0],
                uidvalidity,
            )
        save_cursor(folder, uidvalidity, status["UIDNEXT"] - 1)
        return

    _, last_uid = cursor
    fetched = mailbox.fetch(A(uid=f"{last_uid + 1}:*"), mark_seen=False)
    # 🪤 IMAP's "N:*" always returns the newest message, even when N is past it.
    # Skip anything at or below the cursor so it is never processed twice.
    new_messages = [msg for msg in fetched if _uid_of(msg) > last_uid]

    for msg in new_messages:
        logger.info(
            "Found new email subject=%s date=%s",
            msg.subject,
            msg.date.strftime("%Y-%m-%d %H:%M"),
        )
        process_email_message(msg)
        # 💾 Save after each message, so a later failure does not repeat earlier mail
        save_cursor(folder, uidvalidity, _uid_of(msg))


def _uid_of(msg: MailMessage) -> int:
    """
    Return the UID of a fetched message as an int.

    Raises:
        ValueError: If the server did not send a UID. We always ask for UIDs,
            so this would mean a broken server response.
    """
    if msg.uid is None:
        raise ValueError("Fetched message has no UID")
    return int(msg.uid)


def process_email_message(msg: MailMessage) -> None:
    """
    Processes an email message by checking its subject and arrival time, extracting tickers, and sending notifications.

    Args:
        msg (MailMessage): The email message to process.

    Returns:
        None

    Logs:
        - Info if the email has no subject.
        - Info if the email arrived outside market hours.
        - Warning if no delivery succeeded, so the alert was not recorded.

    Workflow:
        1. Checks if the email has a subject.
        2. Checks if the email arrived during or near market hours.
        3. Extracts ticker symbols from the subject.
        4. Sends notifications to all configured platforms for each extracted ticker.
        5. Records the alert only if at least one delivery succeeded.
    """
    if not msg.subject:
        logger.info("Email has no subject")
        return

    if not is_market_hours_or_near(msg.date):
        logger.info("Email arrived outside market hours")
        return

    tickers = extract_tickers(msg.subject)
    timeframe = extract_timeframe(msg.subject)
    alert_date = msg.date.date() if msg.date else date.today()

    if not is_timeframe_enabled(timeframe):
        logger.info("Timeframe disabled in config timeframe=%s", timeframe)
        return

    for ticker in tickers:
        if should_alert(ticker, timeframe, alert_date):
            delivered = notify_all_platforms(ticker, timeframe)
            # 📝 Record only real deliveries, so a failed alert can be retried later
            if delivered >= 1:
                record_alert(ticker, timeframe, alert_date)
                logger.info("Alert sent ticker=%s timeframe=%s", ticker, timeframe)
            else:
                logger.warning(
                    "No delivery succeeded, alert not recorded ticker=%s timeframe=%s",
                    ticker,
                    timeframe,
                )
        else:
            logger.info(
                "Alert suppressed (duplicate) ticker=%s timeframe=%s",
                ticker,
                timeframe,
            )
