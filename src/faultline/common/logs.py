"""Structured JSON logging shared by every Faultline process.

Each log line is one JSON object carrying at least ``ts``, ``level``, ``service`` and
``event``, so logs from all four processes can be filtered and joined the same way.
"""

from __future__ import annotations

import logging

import structlog

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def configure_logging(service: str, level: str = "INFO") -> None:
    """Send structlog output to stdout as JSON and tag every line with ``service``."""
    if level not in LOG_LEVELS:
        raise ValueError(f"unknown log level {level!r}; expected one of {LOG_LEVELS}")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        # Resolve stdout on every call rather than caching the first logger, so
        # reconfiguration (and pytest's output capture) always takes effect.
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service)
