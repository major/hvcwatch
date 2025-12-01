"""Shared pytest fixtures for hvcwatch tests."""

import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def disable_loguru():
    """Disable loguru output during tests for cleaner output."""
    logger.disable("hvcwatch")
    yield
    logger.enable("hvcwatch")
