"""Structured operation events backed by the file-only Wttch logger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wttch_logging import get_logger, log_path as daily_log_path, log_root


def log_path() -> Path:
    """Return today's unified plugin log path."""
    return daily_log_path()


def runtime_log_path() -> Path:
    """Compatibility alias for callers that previously used a separate file."""
    return daily_log_path()


def record_runtime(message: str) -> None:
    """Record a runtime warning without touching stdout or stderr."""
    try:
        get_logger("runtime").warning(
            message,
            extra={"event": {"operation": "runtime", "result": "warning"}},
        )
    except (OSError, TypeError, ValueError, KeyError):
        return


def record(operation: str, *, result: str = "ok", details: dict[str, Any] | None = None) -> None:
    """追加一条操作记录；日志不可写时不影响插件主流程。

    调用方只能传入经过筛选的元数据。写入异常被吞掉，是为了避免日志目录权限或
    磁盘问题改变 Gate 的原有安全行为。
    """
    event: dict[str, Any] = {"operation": operation, "result": result}
    if details:
        event["details"] = {key: value for key, value in details.items() if value is not None}
    try:
        get_logger("operation").info(operation, extra={"event": event})
    except (OSError, TypeError, ValueError, KeyError):
        return


def query(*, operation: str | None = None, result: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """读取最近的有效记录，并按操作类型和结果筛选。

    查询从尾部截取最近记录，防止日志长期增长后一次性向界面输出全部历史。
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    matches: list[dict[str, Any]] = []
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
