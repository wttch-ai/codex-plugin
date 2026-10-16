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
        """将标准日志记录和可选结构化事件编码为单行 JSON。"""
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
        """吞掉文件写入错误，禁止 logging 默认回退到 stderr。"""
        return


def _configure_root_logger() -> logging.Logger:
    """按当天路径幂等配置唯一文件 Handler，并关闭向根 Logger 传播。"""
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
            # 日期变化、测试目录变化或外部 Handler 注入时统一替换，避免重复写入。
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


def record_runtime(message: str) -> None:
    """Record a runtime warning without touching stdout or stderr."""
    try:
        get_logger("runtime").warning(
            message,
            extra={"event": {"operation": "runtime", "result": "warning"}},
        )
    except (OSError, TypeError, ValueError, KeyError):
        return


def record_operation(
    operation: str,
    *,
    result: str = "ok",
    details: dict[str, Any] | None = None,
) -> None:
    """Append a filtered operation event without affecting plugin behavior."""
    event: dict[str, Any] = {"operation": operation, "result": result}
    if details:
        event["details"] = {
            key: value for key, value in details.items() if value is not None
        }
    try:
        get_logger("operation").info(operation, extra={"event": event})
    except (OSError, TypeError, ValueError, KeyError):
        return


def query_operations(
    *,
    operation: str | None = None,
    result: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent structured operation events matching the filters."""
    if limit < 1:
        raise ValueError("limit must be positive")
    matches: list[dict[str, Any]] = []
    # 跨日按文件名顺序读取，最后统一截取最近的 limit 条匹配记录。
    for path in sorted(log_root().glob("*.log")):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = item.get("event") if isinstance(item, dict) else None
                if not isinstance(event, dict) or "operation" not in event:
                    continue
                if operation and event.get("operation") != operation:
                    continue
                if result and event.get("result") != result:
                    continue
                matches.append({"timestamp": item.get("timestamp"), **event})
    return matches[-limit:]
