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
    override = os.environ.get("WTTCH_PLUGIN_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "wttch-codex-plugin" / "settings.json"


def audit_log_path() -> Path:
    override = os.environ.get("WTTCH_PLUGIN_AUDIT_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "wttch-codex-plugin" / "audit.jsonl"


def valid_default(entry: dict[str, Any]) -> bool:
    feature_type = entry.get("type")
    default = entry.get("default")
    if feature_type == "boolean":
        return isinstance(default, bool)
    if feature_type == "string_list":
        return isinstance(default, list) and all(isinstance(item, str) for item in default)
    return False


def load_feature_catalog(path: Path = FEATURE_CATALOG_PATH) -> dict[str, dict[str, Any]]:
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
    return list(value) if isinstance(value, list) else value


def valid_value(entry: dict[str, Any], value: Any) -> bool:
    if entry["type"] == "boolean":
        return isinstance(value, bool)
    if entry["type"] == "string_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def load_settings() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    catalog = load_feature_catalog()
    values = {key: clone_default(entry["default"]) for key, entry in catalog.items()}
    path = settings_path()
    if not path.exists():
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
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "features": values}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "on", "yes", "1", "enable", "enabled"}:
        return True
    if normalized in {"false", "off", "no", "0", "disable", "disabled"}:
        return False
    raise ValueError("value must be on/off or true/false")


def parse_setting_value(entry: dict[str, Any], value: str) -> Any:
    if entry["type"] == "boolean":
        return parse_boolean(value)
    if entry["type"] == "string_list":
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not valid_value(entry, parsed):
                raise ValueError("value must be a JSON array of strings")
            return parsed
        return [item.strip() for item in stripped.split(",") if item.strip()]
    raise ValueError(f"unsupported setting type: {entry['type']}")


def main(argv: list[str]) -> int:
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
    catalog = load_feature_catalog()
    values = {key: clone_default(entry["default"]) for key, entry in catalog.items()}
    write_settings(values)
    print(json.dumps({"ok": True, "features": values}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
