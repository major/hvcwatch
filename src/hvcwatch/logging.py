"""Centralized logging configuration using loguru."""

import sys

from loguru import logger

# Remove default DEBUG handler and set INFO level with forced colors
# colorize=True forces ANSI colors even without TTY (needed for k8s/stern)
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)

__all__ = ["logger"]
