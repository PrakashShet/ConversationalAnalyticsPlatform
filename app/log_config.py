"""Loguru sink configuration for the application.

Sets up two sinks: INFO to stderr (when there is one — a windowed frozen build
has none) and a rotating DEBUG file at ``<log_dir>/app.log``.

Both sinks run with ``diagnose=False``. Loguru's default, ``diagnose=True``,
annotates every ``logger.exception`` traceback with the *values* of local
variables — and a failed Gemini call has the request object in scope, whose
headers carry ``x-goog-api-key``. With the default, the live API key ended up in
``app.log``. Tracebacks keep their full stack (``backtrace=True``); only the
variable values are dropped.

No Qt, no app imports: the configuration is testable on its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def configure_logging(log_dir: Path) -> Path:
    """Replace loguru's sinks with the app's stderr + file sinks.

    Returns the path of the log file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO", backtrace=True, diagnose=False)
    logger.add(
        str(log_file),
        rotation="1 MB",
        retention=5,
        level="DEBUG",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,  # never print local variable values: they hold secrets
    )
    return log_file
