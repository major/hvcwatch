import logging

import structlog

from hvcwatch.config import settings
from hvcwatch.email_monitor import connect_imap

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


def main() -> None:
    logger.info("Starting HVC Watch email monitor")
    connect_imap(
        settings.imap_host,
        settings.fastmail_user,
        settings.fastmail_pass,
        settings.imap_folder,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
