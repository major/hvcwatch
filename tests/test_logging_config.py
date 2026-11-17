"""Tests for the centralized stdlib logging setup."""

import logging
import sys

import pytest

from hvcwatch.logging_config import setup_logging

LOGGER_NAME = "hvcwatch"


@pytest.fixture
def hvcwatch_logger():
    """Give each test a clean hvcwatch logger and restore it afterwards."""
    logger = logging.getLogger(LOGGER_NAME)
    saved_level = logger.level
    saved_handlers = logger.handlers[:]
    for handler in saved_handlers:
        logger.removeHandler(handler)
    yield logger
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        logger.addHandler(handler)
    logger.setLevel(saved_level)


def test_setup_logging_adds_stderr_handler_at_requested_level(hvcwatch_logger):
    # Arrange: hvcwatch_logger starts with no handlers

    # Act
    setup_logging("DEBUG")

    # Assert
    assert hvcwatch_logger.level == logging.DEBUG
    [handler] = hvcwatch_logger.handlers
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr


def test_setup_logging_twice_does_not_duplicate_handlers(hvcwatch_logger):
    # Arrange: hvcwatch_logger starts with no handlers

    # Act
    setup_logging()
    setup_logging()

    # Assert
    assert len(hvcwatch_logger.handlers) == 1
