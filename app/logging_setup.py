"""Stdlib + structlog logging configuration with the two-layer secret scrubber.

This module is imported exactly once at app startup (before anything that
might log a secret — scheduler, FastAPI handlers, DB session factory). After
``configure_logging`` returns, every log path in the process is guarded by
``RedactingFilter`` (stdlib) and ``structlog_scrub_processor`` (structlog).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog

from app.security.log_scrubber import RedactingFilter, structlog_scrub_processor

# Loggers known to emit verbose INFO noise that can bypass application-level
# filtering if attached to their own handlers. We throttle them to WARNING and
# rely on the root logger's RedactingFilter for anything that does come through.
_NOISY_LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error",
                  "apscheduler", "apscheduler.scheduler", "apscheduler.executors.default",
                  "sqlalchemy", "sqlalchemy.engine", "sqlalchemy.pool")


def configure_logging(level: str, log_dir: Path) -> None:
    """Wire stdlib + structlog with redaction filters.

    Args:
        level: Log level name (e.g. "INFO", "DEBUG").
        log_dir: Directory for the ``app.log`` file sink. Created if missing.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    level_int = logging.getLevelName(level.upper())
    if not isinstance(level_int, int):
        level_int = logging.INFO

    redacting_filter = RedactingFilter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(redacting_filter)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.addFilter(redacting_filter)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    stdout_handler.setFormatter(fmt)
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers = [stdout_handler, file_handler]
    root.setLevel(level_int)

    for noisy in _NOISY_LOGGERS:
        lg = logging.getLogger(noisy)
        lg.setLevel(logging.WARNING)
        # Ensure they propagate to root (so RedactingFilter applies) and do not
        # carry their own handlers that would bypass the filter.
        lg.handlers = []
        lg.propagate = True

    # structlog chain — scrub BEFORE JSONRenderer so we mutate typed values,
    # not a rendered string where escapes may have shifted regex boundaries.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog_scrub_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
