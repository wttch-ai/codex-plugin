#!/usr/bin/env python3
"""读取项目 ``.agents/wttch/config.yml`` 中的 Wttch 功能设置。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from operation_log import log_path, query as query_operations, record as record_operation
from paths import DEFAULT_AUDIT_LOG_PATH
from wttch_config import CONFIG_PATH, load_config


# 此处只描述 YAML 结构，不保存任何配置值或默认值；功能值必须来自调用项目。
FEATURE_SCHEMA: dict[str, dict[str, Any]] = {
    "jev_gate": {"type": "boolean"},
    "openrouter_review": {"type": "boolean"},
    "show_decision_reason": {"type": "boolean"},
    "audit_log": {"type": "boolean"},
    "model_gate": {"type": "boolean"},
    "model_gate_action": {"type": "string", "choices": ["block", "warn"]},
    "blocked_models": {"type": "string_list"},
}


def audit_log_path() -> Path:
    """返回本机 JSONL 审计日志位置，支持用环境变量隔离测试数据。"""
    override = os.environ.get("WTTCH_PLUGIN_AUDIT_LOG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_AUDIT_LOG_PATH


def valid_value(entry: dict[str, Any], value: Any) -> bool:
    """校验项目 YAML 中的单个功能值。"""
    if entry["type"] == "boolean":
        return isinstance(value, bool)
    if entry["type"] == "string_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if entry["type"] == "string":
        return isinstance(value, str) and value in entry.get("choices", [])
    return False


def load_settings(working_directory: Path | None = None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """只从调用项目的 ``.agents/wttch/config.yml`` 读取并校验功能设置。"""
    data = load_config(working_directory)
    values = data.get("features")
    config_path = (working_directory or Path.cwd()) / CONFIG_PATH
    if not isinstance(values, dict):
        raise ValueError(f"{config_path} features must be an object")
    unexpected = set(values) - set(FEATURE_SCHEMA)
    if unexpected:
        raise ValueError(f"unknown feature in {config_path}: {sorted(unexpected)[0]}")
    missing = set(FEATURE_SCHEMA) - set(values)
    if missing:
        raise ValueError(f"missing feature in {config_path}: {sorted(missing)[0]}")
    for key, value in values.items():
        if not valid_value(FEATURE_SCHEMA[key], value):
            raise ValueError(f"feature {key} has an invalid value in {config_path}")
    return dict(values), FEATURE_SCHEMA


def main(argv: list[str]) -> int:
    """提供只读设置和操作日志查询入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-settings")
    query_parser = subparsers.add_parser("query-log")
    query_parser.add_argument("--operation")
    query_parser.add_argument("--result")
    query_parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    if args.command == "list-settings":
        values, _ = load_settings()
        record_operation("settings.list")
        print(json.dumps({"config_file": str(Path.cwd() / CONFIG_PATH), "features": values}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"log_file": str(log_path()), "entries": query_operations(
        operation=args.operation, result=args.result, limit=args.limit
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
