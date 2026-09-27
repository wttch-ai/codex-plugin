"""统一的插件操作日志：只记录安全的元数据，不记录输入正文或密钥。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

# 默认位置集中在 paths.py；这里仍允许用环境变量隔离测试或切换本机存储位置。
from paths import DEFAULT_OPERATION_LOG_PATH


def log_path() -> Path:
    """返回当前操作日志路径，环境变量优先于统一的本机默认路径。"""
    override = os.environ.get("WTTCH_PLUGIN_OPERATION_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_OPERATION_LOG_PATH


def record(operation: str, *, result: str = "ok", details: dict[str, Any] | None = None) -> None:
    """追加一条操作记录；日志不可写时不影响插件主流程。

    调用方只能传入经过筛选的元数据。写入异常被吞掉，是为了避免日志目录权限或
    磁盘问题改变 Gate 的原有安全行为。
    """
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "result": result,
    }
    # 删除 None 字段，避免日志中出现没有实际信息的占位值。
    if details:
        entry["details"] = {key: value for key, value in details.items() if value is not None}
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # JSONL 采用追加模式，每行一条完整事件，便于流式读取和部分损坏时跳过坏行。
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError):
        return


def query(*, operation: str | None = None, result: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """读取最近的有效记录，并按操作类型和结果筛选。

    查询从尾部截取最近记录，防止日志长期增长后一次性向界面输出全部历史。
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    path = log_path()
    if not path.exists():
        return []
    matches: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                # 单行解析失败不影响其余历史记录的查询。
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if operation and item.get("operation") != operation:
                continue
            if result and item.get("result") != result:
                continue
            matches.append(item)
    return matches[-limit:]
