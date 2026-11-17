import logging

from hvcwatch import config
from hvcwatch.email_monitor import connect_imap
from hvcwatch.logging_config import setup_logging
from hvcwatch.version import get_version_info

logger = logging.getLogger(__name__)


def main() -> None:
    """
    🚀 Start the IMAP monitor.

    Loads settings first, so missing config fails at startup, before logging starts.
    """
    settings = config.get_settings()
    setup_logging()

    version_info = get_version_info()
    logger.info("Starting HVC Watch email monitor version=%s", version_info)
    connect_imap(
        settings.imap_host,
        settings.fastmail_user,
        settings.fastmail_pass,
        settings.imap_folder,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
