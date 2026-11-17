"""Centralized stdlib logging setup for hvcwatch."""

import logging
import sys

LOGGER_NAME = "hvcwatch"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(level: int | str = logging.INFO) -> None:
    """
    Configure the hvcwatch logger to write to stderr.

    Safe to call more than once. Each call replaces the handler added by an
    earlier call, so messages never print twice.

    Args:
        level: Minimum level to emit, as a logging constant or name (e.g., "DEBUG")
    """
    # 🎯 Configure only our logger so third-party INFO logs stay quiet
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level)
