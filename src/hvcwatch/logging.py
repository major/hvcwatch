"""Centralized logging configuration using loguru."""

import sys

from loguru import logger

# Remove default DEBUG handler and set INFO level
logger.remove()
logger.add(sys.stderr, level="INFO")

__all__ = ["logger"]
