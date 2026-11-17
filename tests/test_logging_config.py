"""Tests for the centralized stdlib logging setup, checked through what reaches stderr."""

import logging
import re

import pytest

from hvcwatch.logging_config import setup_logging

# 🧩 Timestamp, level padded to 8 characters, logger name, then the message
HELLO_LINE = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} INFO     hvcwatch\.test: hello"

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


def test_default_level_shows_info_in_the_expected_format(capsys):
    """📝 INFO lines show a timestamp, level, logger name, and message. DEBUG stays hidden."""
    # Arrange
    child = logging.getLogger("hvcwatch.test")

    # Act
    setup_logging()
    child.info("hello")
    child.debug("hidden")

    # Assert
    err = capsys.readouterr().err
    assert "hidden" not in err
    [line] = err.splitlines()
    assert re.fullmatch(HELLO_LINE, line)


def test_debug_level_shows_debug_lines(capsys):
    """🐞 Asking for DEBUG lets debug messages through."""
    # Arrange
    child = logging.getLogger("hvcwatch.test")

    # Act
    setup_logging("DEBUG")
    child.debug("details")

    # Assert
    assert "hvcwatch.test: details" in capsys.readouterr().err


def test_repeated_setup_prints_each_line_once(capsys):
    """🔁 Calling setup_logging twice does not make each line print twice."""
    # Act
    setup_logging()
    setup_logging()
    logging.getLogger("hvcwatch.test").info("hello")

    # Assert
    assert capsys.readouterr().err.count("hvcwatch.test: hello") == 1


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
