"""File-only logging for the Wttch plugin.

The logger deliberately owns no console handler because Hook stdout is a protocol
channel.  Every record is one JSON object in ``~/.wttch/logs/YYYY-MM-DD.log``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any

from paths import DEFAULT_LOG_ROOT


LOGGER_NAME = "wttch"
_MANAGED_HANDLER = "_wttch_file_handler"
_LOCK = RLock()


def log_root() -> Path:
    """Return the daily log directory; the override exists for isolated tests."""
    override = os.environ.get("WTTCH_PLUGIN_LOG_DIR", "").strip()
    return Path(override).expanduser() if override else DEFAULT_LOG_ROOT


def log_path(moment: datetime | None = None) -> Path:
    """Return the log file for the local calendar day."""
    current = moment or datetime.now().astimezone()
    return log_root() / f"{current:%Y-%m-%d}.log"


class JsonLineFormatter(logging.Formatter):
    """Serialize a LogRecord without writing arbitrary object representations."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, dict):
            payload["event"] = event
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class SilentFileHandler(logging.FileHandler):
    """A FileHandler whose write failures never fall back to stderr."""

    def handleError(self, record: logging.LogRecord) -> None:
        return


def _configure_root_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    desired_path = log_path().resolve()
    with _LOCK:
        for handler in list(logger.handlers):
            if getattr(handler, _MANAGED_HANDLER, False):
                current_path = Path(handler.baseFilename).resolve()
                if current_path == desired_path:
                    logger.setLevel(logging.INFO)
                    logger.propagate = False
                    return logger
            logger.removeHandler(handler)
            handler.close()

        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            desired_path.parent.mkdir(parents=True, exist_ok=True)
            handler = SilentFileHandler(desired_path, encoding="utf-8")
            setattr(handler, _MANAGED_HANDLER, True)
            handler.setFormatter(JsonLineFormatter())
            logger.addHandler(handler)
        except (OSError, TypeError, ValueError):
            # NullHandler also suppresses logging.lastResort, which writes to stderr.
            logger.addHandler(logging.NullHandler())
        return logger


def get_logger(component: str) -> logging.Logger:
    """Return a child logger that can only propagate to the managed file logger."""
    _configure_root_logger()
    logger = logging.getLogger(f"{LOGGER_NAME}.{component}")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return logger
