#!/usr/bin/env python3
"""读取项目功能开关，并提供安全的设置索引与日志查询 CLI。

功能值只来自调用项目的 ``.agents/wttch/config.yml``，不存在插件内默认配置覆盖链。
JEV Hook 是否启用由项目决策 YAML 决定，因此不再出现在功能开关中；本模块当前只校验
模型 Gate。CLI 的日志查询必须由用户主动调用，Hook 运行期间不会读取或回显日志内容。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from wttch_logging import log_path, query_log, record_operation
from wttch_config import CONFIG_PATH, load_config


# 此处只描述仍由 config.yml 控制的模型 Gate 结构，不保存任何配置值或默认值。
# JEV 的启用状态由 .agents/wttch/jev-decisions/*.yml 是否声明 Hook 决定，不能在这里
# 再维护第二套开关，否则配置与决策文件可能互相冲突。
FEATURE_SCHEMA: dict[str, dict[str, Any]] = {
    "model_gate": {"type": "boolean"},
    "model_gate_action": {"type": "string", "choices": ["block", "warn"]},
    "blocked_models": {"type": "string_list"},
}


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
    # Project configuration is optional.  A malformed `features` value must
    # not prevent hooks from running; fall back to the built-in defaults.
    if not isinstance(values, dict):
        return {}
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
    """提供只读设置索引与日志查询入口。

    ``list-settings`` 只展示项目配置字段，不显示值；``query-log`` 是用户主动调用的
    诊断命令，可按日志级别和整行关键词筛选。Hook 执行路径不会自动调用查询命令，
    因而不会把历史日志内容带入协议输出。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-settings")
    query_parser = subparsers.add_parser("query-log")
    query_parser.add_argument("--keyword", help="按整行字面包含关系筛选日志。")
    query_parser.add_argument("--level", help="按日志级别筛选，不区分输入大小写。")
    query_parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    if args.command == "list-settings":
        values, _ = load_settings()
        record_operation("settings.list")
        print(json.dumps({"config_file": str(Path.cwd() / CONFIG_PATH), "features": values}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"log_file": str(log_path()), "entries": query_log(
        keyword=args.keyword, level=args.level, limit=args.limit
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
