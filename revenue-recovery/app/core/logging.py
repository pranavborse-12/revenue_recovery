"""
Structured logging setup.

Goals for Phase 1:
  - Every log line is timestamped and tagged with a logger name and level,
    so we can tell at a glance where a message came from.
  - We NEVER log secrets: Razorpay key secret, webhook secret, or raw
    Authorization headers. This module doesn't scrub strings automatically
    (that's error-prone) -- instead, the discipline is: calling code must
    never pass a secret into a log call. We enforce this via code review /
    convention, and by keeping secret values out of the objects we log
    (see app/services/webhook_service.py for how event payloads are
    logged without leaking sensitive customer/payment fields).
  - Logs are human-readable in development. If this were a Phase-N
    production concern, we'd switch to JSON logs for log aggregation --
    not needed yet.
"""

import logging
import sys

from app.core.config import get_settings


def configure_logging() -> None:
    """
    Configure the root logger once, at application startup.

    Call this exactly once, from app/main.py, before the app starts
    handling requests.
    """
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)

    # Avoid duplicate handlers if configure_logging() is somehow called
    # more than once (e.g. under a test runner that imports main twice).
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Uvicorn's own loggers are noisy at DEBUG; leave them at their
    # defaults unless the operator explicitly wants verbose output.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger, e.g. get_logger(__name__)."""
    return logging.getLogger(name)
