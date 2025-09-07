"""
Global logging configuration for this project.

Python automatically imports `sitecustomize` (if present on sys.path) at process
startup, so this makes colorized WARNING/ERROR output available everywhere
without touching individual files.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional


FMT = "%(asctime)s %(levelname)s %(name)s [%(filename)s]: %(message)s"


class ColorFormatter(logging.Formatter):
    RESET = "\x1b[0m"
    COLORS = {
        logging.WARNING: "\x1b[33m",    # Yellow
        logging.ERROR: "\x1b[31m",      # Red
        logging.CRITICAL: "\x1b[31;1m",  # Bright Red
    }

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self.COLORS.get(record.levelno)
        if color and _tty_supports_color():
            return f"{color}{text}{self.RESET}"
        return text


def _tty_supports_color() -> bool:
    # Respect NO_COLOR (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False
    # Only colorize when stderr/stdout are TTYs
    try:
        return sys.stderr.isatty() or sys.stdout.isatty()
    except Exception:
        return False


def _ensure_root_stream_handler() -> None:
    root = logging.getLogger()
    # Don’t clobber explicit user configuration; only set INFO if unset
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    has_stream = False
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            has_stream = True
            # Apply color-capable formatter with filename for all root stream handlers
            h.setFormatter(ColorFormatter(FMT))

    if not has_stream:
        sh = logging.StreamHandler()  # defaults to sys.stderr
        sh.setLevel(logging.INFO)
        sh.setFormatter(ColorFormatter(FMT))
        root.addHandler(sh)


# Apply on import
try:
    _ensure_root_stream_handler()
except Exception:
    # Never let logging setup crash the process
    pass
