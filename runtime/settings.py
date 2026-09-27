#!/usr/bin/env python3
"""读取和更新 Wttch 插件功能设置。"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FEATURE_CATALOG_PATH = PLUGIN_ROOT / "config" / "features.json"


def settings_path() -> Path:
    """返回本机设置文件位置，测试或自动化可通过环境变量覆盖默认路径。"""
    override = os.environ.get("WTTCH_PLUGIN_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "wttch-codex-plugin" / "settings.json"


def audit_log_path() -> Path:
    """返回本机 JSONL 审计日志位置，支持用环境变量隔离测试数据。"""
    override = os.environ.get("WTTCH_PLUGIN_AUDIT_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "wttch-codex-plugin" / "audit.jsonl"


def valid_default(entry: dict[str, Any]) -> bool:
    """校验功能目录中的默认值是否符合其声明类型和候选值范围。"""
    feature_type = entry.get("type")
    default = entry.get("default")
    if feature_type == "boolean":
        return isinstance(default, bool)
    if feature_type == "string_list":
        return isinstance(default, list) and all(isinstance(item, str) for item in default)
    if feature_type == "string":
        choices = entry.get("choices", [])
        return isinstance(default, str) and (not choices or default in choices)
    return False


def load_feature_catalog(path: Path = FEATURE_CATALOG_PATH) -> dict[str, dict[str, Any]]:
    """读取功能目录，并在合并用户设置前严格校验其结构。

    目录是所有可接受配置的唯一来源；尽早拒绝无效键、重复键和无效默认值，可避免
    错误配置在 Hook 执行期间产生不确定行为。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("feature catalog version must be 1")
    entries = data.get("features")
    if not isinstance(entries, list):
        raise ValueError("feature catalog requires a features array")
    catalog: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"features[{index}] must be an object")
        key = entry.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError(f"features[{index}].key is invalid")
        if key in catalog:
            raise ValueError(f"duplicate feature key: {key}")
        if not valid_default(entry):
            raise ValueError(f"feature {key} has an unsupported type or invalid default")
        if not isinstance(entry.get("label"), str) or not isinstance(
            entry.get("description"), str
        ):
            raise ValueError(f"feature {key} requires label and description")
        catalog[key] = entry
    return catalog


def clone_default(value: Any) -> Any:
    """复制可变默认值，避免调用方修改列表后污染后续加载结果。"""
    return list(value) if isinstance(value, list) else value


def valid_value(entry: dict[str, Any], value: Any) -> bool:
    """根据目录条目的类型约束校验一个实际设置值。"""
    if entry["type"] == "boolean":
        return isinstance(value, bool)
    if entry["type"] == "string_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if entry["type"] == "string":
        choices = entry.get("choices", [])
        return isinstance(value, str) and (not choices or value in choices)
    return False


def load_settings() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """以目录默认值为基线，加载并验证本机覆盖项。

    设置文件可以只保存被用户修改过的条目。未保存的条目继续采用目录默认值，因此
    新版本新增的功能开关也能自然获得默认配置。
    """
    catalog = load_feature_catalog()
    values = {key: clone_default(entry["default"]) for key, entry in catalog.items()}
    path = settings_path()
    if not path.exists():
        # 第一次使用时不创建文件，调用方可直接获得完整的默认设置。
        return values, catalog
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("features", {}), dict):
        raise ValueError(f"settings file is invalid: {path}")
    for key, value in data["features"].items():
        if key not in catalog:
            raise ValueError(f"unknown feature in settings file: {key}")
        if not valid_value(catalog[key], value):
            raise ValueError(f"feature {key} has an invalid value")
        values[key] = value
    return values, catalog


def write_settings(values: dict[str, Any]) -> None:
    """原子替换本机设置文件，避免进程中断留下半个 JSON 文件。"""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "features": values}, indent=2) + "\n",
        encoding="utf-8",
    )
    # 同目录内的 replace 是原子操作，读者只能看到旧文件或完整的新文件。
    temporary.replace(path)


def parse_boolean(value: str) -> bool:
    """把命令行中常用的布尔拼写转换为 Python 布尔值。"""
    normalized = value.strip().lower()
    if normalized in {"true", "on", "yes", "1", "enable", "enabled"}:
        return True
    if normalized in {"false", "off", "no", "0", "disable", "disabled"}:
        return False
    raise ValueError("value must be on/off or true/false")


def parse_setting_value(entry: dict[str, Any], value: str) -> Any:
    """按功能类型解析命令行值，并在写入前校验候选值。"""
    if entry["type"] == "boolean":
        return parse_boolean(value)
    if entry["type"] == "string_list":
        stripped = value.strip()
        if stripped.startswith("["):
            # 列表以 JSON 形式提供时可保留包含逗号的单个元素。
            parsed = json.loads(stripped)
            if not valid_value(entry, parsed):
                raise ValueError("value must be a JSON array of strings")
            return parsed
        return [item.strip() for item in stripped.split(",") if item.strip()]
    if entry["type"] == "string":
        stripped = value.strip().lower()
        if not valid_value(entry, stripped):
            choices = ", ".join(entry.get("choices", []))
            raise ValueError(f"value must be one of: {choices}")
        return stripped
    raise ValueError(f"unsupported setting type: {entry['type']}")


def main(argv: list[str]) -> int:
    """提供列出、更新和恢复本机功能设置的命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-settings")
    set_parser = subparsers.add_parser("set-setting")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    subparsers.add_parser("reset-settings")
    args = parser.parse_args(argv)

    if args.command == "list-settings":
        values, catalog = load_settings()
        print(
            json.dumps(
                {
                    "settings_file": str(settings_path()),
                    "features": [
                        {**entry, "value": values[key]}
                        for key, entry in catalog.items()
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "set-setting":
        values, catalog = load_settings()
        if args.key not in catalog:
            raise ValueError(f"unknown feature: {args.key}")
        values[args.key] = parse_setting_value(catalog[args.key], args.value)
        write_settings(values)
        print(json.dumps({"ok": True, "key": args.key, "value": values[args.key]}))
        return 0
    # reset-settings 不依赖旧文件内容，直接用当前目录中的默认值完整覆盖。
    catalog = load_feature_catalog()
    values = {key: clone_default(entry["default"]) for key, entry in catalog.items()}
    write_settings(values)
    print(json.dumps({"ok": True, "features": values}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
