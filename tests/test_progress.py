from __future__ import annotations

import io
import logging

from video_agent.progress import LOGGER_NAME, configure_logging


def test_console_log_format_includes_source_filename_and_line() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    previous_handlers = list(logger.handlers)
    logger.handlers.clear()
    try:
        configured = configure_logging(io.StringIO())
        handler = next(
            handler
            for handler in configured.handlers
            if getattr(handler, "_video_agent_console", False)
        )
        record = configured.makeRecord(
            LOGGER_NAME,
            logging.INFO,
            "C:/workspace/example_stage.py",
            42,
            "stage message",
            (),
            None,
        )
        rendered = handler.format(record)
    finally:
        logger.handlers.clear()
        logger.handlers.extend(previous_handlers)

    assert "example_stage.py:42" in rendered
    assert rendered.endswith("stage message")
