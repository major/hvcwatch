import sentry_sdk

from hvcwatch.config import settings
from hvcwatch.email_monitor import connect_imap
from hvcwatch.logging import logger
from hvcwatch.version import get_version_info


def main() -> None:
    # Initialize Sentry if DSN is provided
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            # Enable automatic breadcrumbs for common libraries
            integrations=[],
            # Attach local variables to exceptions for better debugging
            attach_stacktrace=True,
        )
        logger.info(
            "Sentry initialized environment={environment} traces_sample_rate={traces_sample_rate}",
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
        )

    version_info = get_version_info()
    logger.info(
        "Starting HVC Watch email monitor version={version}", version=version_info
    )
    connect_imap(
        settings.imap_host,
        settings.fastmail_user,
        settings.fastmail_pass,
        settings.imap_folder,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
