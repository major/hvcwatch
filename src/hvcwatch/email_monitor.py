import logging

import sentry_sdk
import structlog
from imap_tools.mailbox import BaseMailBox, MailBox
from imap_tools.message import MailMessage
from imap_tools.query import AND, A

from hvcwatch.notification import notify_all_platforms
from hvcwatch.utils import extract_tickers, is_market_hours_or_near

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


def connect_imap(host: str, user: str, password: str, folder: str) -> None:
    """
    Connects to an IMAP mailbox and monitors for new emails using simple polling.

    Args:
        host (str): The IMAP server hostname.
        user (str): The username for authentication.
        password (str): The password for authentication.
        folder (str): The mailbox folder to monitor.

    Raises:
        KeyboardInterrupt: If monitoring is interrupted by the user.

    Side Effects:
        Logs monitoring start and stop events.
        Calls get_unread_messages and monitor_mailbox to process emails.
    """
    """Monitor for new emails using simple polling"""
    sentry_sdk.add_breadcrumb(
        category="imap",
        message=f"Connecting to IMAP server {host}",
        level="info",
        data={"host": host, "user": user, "folder": folder},
    )

    with MailBox(host).login(user, password, folder) as mailbox:
        get_unread_messages(mailbox)

        try:
            logger.info("Starting email monitoring")
            sentry_sdk.add_breadcrumb(
                category="imap",
                message="Started email monitoring",
                level="info",
            )
            monitor_mailbox(mailbox)
        except KeyboardInterrupt:  # pragma: no cover
            logger.info("Stopping email monitoring")


def monitor_mailbox(mailbox: BaseMailBox) -> None:
    """
    Monitors the given mailbox for new emails using the IDLE protocol.

    Continuously polls the mailbox for new messages. When a new email is detected,
    logs the event and prints the date and subject of each unseen message, marking
    them as seen after processing.

    Args:
        mailbox (BaseMailBox): The mailbox instance to monitor for incoming emails.
    """
    while True:
        with mailbox.idle as idle:
            responses = idle.poll(timeout=10)

        if responses:
            logger.info("New email detected while IDLE")
            for msg in mailbox.fetch(A(seen=False), mark_seen=True):
                process_email_message(msg)


def get_unread_messages(mailbox: BaseMailBox) -> None:
    """
    Fetches unread email messages from the provided mailbox, marks them as seen, and processes each message.

    Args:
        mailbox (BaseMailBox): The mailbox instance to fetch unread messages from.

    Returns:
        None

    Logs:
        - The start of the unread message check.
        - The number of unread messages found.
        - The subject and date of each unread email processed.
    """
    logger.info("Checking for unread messages")
    unread_messages = list(mailbox.fetch(AND(seen=False), mark_seen=True))

    if not unread_messages:
        return

    logger.info(f"Processing {len(unread_messages)} unread messages")

    for msg in unread_messages:
        logger.info(
            "Found unread email",
            subject=msg.subject,
            date=msg.date.strftime("%Y-%m-%d %H:%M"),
        )
        process_email_message(msg)


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

    Workflow:
        1. Checks if the email has a subject.
        2. Checks if the email arrived during or near market hours.
        3. Extracts ticker symbols from the subject.
        4. Sends notifications to all configured platforms for each extracted ticker.
    """
    sentry_sdk.add_breadcrumb(
        category="email",
        message="Processing email message",
        level="info",
        data={
            "subject": msg.subject,
            "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else None,
        },
    )

    if not msg.subject:
        logger.info("Email has no subject")
        return

    if not is_market_hours_or_near(msg.date):
        logger.info("Email arrived outside market hours")
        sentry_sdk.add_breadcrumb(
            category="email",
            message="Email rejected - outside market hours",
            level="info",
        )
        return

    tickers = extract_tickers(msg.subject)
    sentry_sdk.add_breadcrumb(
        category="email",
        message=f"Extracted {len(tickers)} ticker(s)",
        level="info",
        data={"tickers": tickers},
    )

    for ticker in tickers:
        notify_all_platforms(ticker)
