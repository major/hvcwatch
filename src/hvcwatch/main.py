import logging

import structlog

from hvcwatch.config import settings
from hvcwatch.email_monitor import connect_imap
from hvcwatch.version import get_version_info

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


def main() -> None:
    version_info = get_version_info()
    logger.info("Starting HVC Watch email monitor", version=version_info)
    connect_imap(
        settings.imap_host,
        settings.fastmail_user,
        settings.fastmail_pass,
        settings.imap_folder,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
