"""Centralized stdlib logging setup for hvcwatch."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

LOGGER_NAME = "hvcwatch"

# 🧮 Attributes every LogRecord has, so any other attribute came from `extra=`
STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """
    Format each log record as one JSON object, which tools such as `hl` can read.

    Every entry has timestamp (UTC), level, logger, and message. It also has
    exception when the record carries exc_info. Values passed with `extra=`
    become top-level keys. When an extra has the same name as a core field,
    the core field wins.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Build the JSON line for one record.

        Args:
            record: The log record to format

        Returns:
            One line of JSON. Newlines inside tracebacks are escaped, so the line stays whole.
        """
        # 🕒 Millisecond precision, always UTC, so hl and other readers sort entries reliably
        core: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            core["exception"] = self.formatException(record.exc_info)

        extras = {
            key: value
            for key, value in vars(record).items()
            if key not in STANDARD_ATTRS and key not in core
        }
        # 🛟 default=str keeps logging alive when an extra value is not JSON-serializable
        return json.dumps({**core, **extras}, default=str)


def setup_logging(level: int | str = logging.INFO) -> None:
    """
    Configure the hvcwatch logger to write JSON lines to stderr.

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
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
