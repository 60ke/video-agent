from __future__ import annotations

import logging
import sys
from typing import TextIO


LOGGER_NAME = "video_agent"


def configure_logging(stream: TextIO | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not any(getattr(handler, "_video_agent_console", False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        handler._video_agent_console = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
