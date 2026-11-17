"""Tests for the centralized stdlib logging setup, checked through what reaches stderr."""

import json
import logging
import sys
from datetime import datetime, timedelta

import pytest

from hvcwatch.logging_config import JsonFormatter, setup_logging

# 📜 Every test configures the hvcwatch logger, so it is cleaned up after each
pytestmark = pytest.mark.usefixtures("hvcwatch_logger")


class CloseRecorder(logging.Handler):
    """🧾 A handler that remembers whether it was closed."""

    def __init__(self) -> None:
        """Start as open, with no records."""
        super().__init__()
        self.closed_flag = False

    def close(self) -> None:
        """Remember that close ran, then do the normal handler cleanup."""
        self.closed_flag = True
        super().close()


def make_record(msg: str, args: tuple = (), exc_info=None) -> logging.LogRecord:
    """
    🧾 Build a bare INFO record from the hvcwatch.test logger.

    Args:
        msg: The %-style message template
        args: Values to fill into the template
        exc_info: Optional exception info tuple, as from sys.exc_info()

    Returns:
        A LogRecord ready to pass to a formatter
    """
    return logging.LogRecord(
        "hvcwatch.test", logging.INFO, __file__, 1, msg, args, exc_info
    )


def json_lines(text: str) -> list[dict]:
    """
    🧾 Parse every line of captured output as a JSON object.

    Args:
        text: Captured stderr text

    Returns:
        One dict per line. A line that is not JSON makes the test fail.
    """
    return [json.loads(line) for line in text.splitlines()]


def test_default_level_writes_info_as_one_json_line(capsys):
    """📝 With the default level, INFO becomes one JSON line on stderr. DEBUG stays hidden."""
    # Arrange
    child = logging.getLogger("hvcwatch.test")

    # Act
    setup_logging()
    child.info("hello")
    child.debug("hidden")

    # Assert
    err = capsys.readouterr().err
    assert "hidden" not in err
    [entry] = json_lines(err)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "hvcwatch.test"
    assert entry["message"] == "hello"


def test_debug_level_shows_debug_lines(capsys):
    """🐞 Asking for DEBUG lets debug messages through."""
    # Arrange
    child = logging.getLogger("hvcwatch.test")

    # Act
    setup_logging("DEBUG")
    child.debug("details")

    # Assert
    [entry] = json_lines(capsys.readouterr().err)
    assert entry["level"] == "DEBUG"
    assert entry["message"] == "details"


def test_repeated_setup_prints_each_line_once(capsys):
    """🔁 Calling setup_logging twice does not make each line print twice."""
    # Act
    setup_logging()
    setup_logging()
    logging.getLogger("hvcwatch.test").info("hello")

    # Assert
    assert len(json_lines(capsys.readouterr().err)) == 1


def test_third_party_info_logs_stay_quiet(capsys):
    """🤫 INFO from a third-party library such as urllib3 is not printed."""
    # Act
    setup_logging()
    logging.getLogger("urllib3").info("noisy")

    # Assert
    assert capsys.readouterr().err == ""


def test_second_setup_closes_and_removes_the_earlier_handler():
    """🧹 Each call replaces the previous handler, closing it first."""
    # Arrange
    earlier = CloseRecorder()
    logging.getLogger("hvcwatch").addHandler(earlier)

    # Act
    setup_logging()

    # Assert
    assert earlier.closed_flag
    assert earlier not in logging.getLogger("hvcwatch").handlers


def test_formatter_writes_core_fields_with_a_utc_timestamp():
    """🕒 A record becomes one JSON object with a UTC timestamp, level, logger, and filled-in message."""
    # Arrange
    record = make_record("Discord response status_code=%s", args=(204,))

    # Act
    line = JsonFormatter().format(record)

    # Assert
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["level"] == "INFO"
    assert entry["logger"] == "hvcwatch.test"
    assert entry["message"] == "Discord response status_code=204"
    timestamp = datetime.fromisoformat(entry["timestamp"])
    assert timestamp.utcoffset() == timedelta(0)
    assert abs(timestamp.timestamp() - record.created) < 0.001


def test_exc_info_adds_exception_and_stays_on_one_line():
    """💥 A traceback goes into an `exception` key, escaped so the entry is still one line."""
    # Arrange
    try:
        raise ValueError("boom")
    except ValueError:
        record = make_record("failed", exc_info=sys.exc_info())

    # Act
    line = JsonFormatter().format(record)

    # Assert
    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["exception"]


def test_extra_fields_become_top_level_keys_and_unserializable_values_do_not_crash(
    capsys,
):
    """🧩 Values from `extra=` appear at the top level. An object that is not JSON still gets logged."""
    # Arrange
    setup_logging()
    marker = object()

    # Act
    logging.getLogger("hvcwatch.test").info(
        "order placed", extra={"ticker": "AAPL", "blob": marker}
    )

    # Assert
    [entry] = json_lines(capsys.readouterr().err)
    assert entry["ticker"] == "AAPL"
    assert entry["blob"] == str(marker)


def test_plain_record_has_only_core_keys():
    """🧼 Without exc_info or extras, the entry has no `exception` key and no standard LogRecord attributes."""
    # Arrange
    record = make_record("hello")

    # Act
    entry = json.loads(JsonFormatter().format(record))

    # Assert
    assert set(entry) == {"timestamp", "level", "logger", "message"}
