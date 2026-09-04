"""Rotating crash log plus process and thread exception hooks."""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import __version__
from .paths import diagnostics_dir, ensure_app_directories

LOGGER_NAME = "discord_overlay"
LOG_FILE_NAME = "discord-overlay.log"


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_crash_logging() -> logging.Logger:
    """Install a bounded log file and route unhandled exceptions into it."""
    ensure_app_directories()
    log = logger()
    log.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) for handler in log.handlers):
        handler = RotatingFileHandler(
            diagnostics_dir() / LOG_FILE_NAME, maxBytes=1_000_000, backupCount=3, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        log.addHandler(handler)

    def process_hook(exc_type, exc_value, exc_traceback) -> None:
        log.critical("Unhandled process exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def thread_hook(args) -> None:
        log.critical(
            "Unhandled thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = process_hook
    threading.excepthook = thread_hook
    log.info("Discord Overlay %s session started", __version__)
    return log
