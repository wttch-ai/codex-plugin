#!/usr/bin/env python3
"""显示 Wttch 插件当前已配置的项目，不显示任何配置值。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from settings import settings_path
from wttch_config import configured_fields


# 仅枚举本插件实际读取的环境变量，避免把无关进程环境带入输出。
CONFIGURATION_ENVIRONMENT_VARIABLES = (
    "OPENROUTER_API_KEY",
    "JEV_OPENROUTER_MODEL",
    "JEV_OPENROUTER_BASE_URL",
    "JEV_OPENROUTER_TIMEOUT",
    "WTTCH_PLUGIN_SETTINGS_FILE",
    "WTTCH_PLUGIN_AUDIT_LOG",
)


def setting_overrides() -> list[str]:
    """返回设置文件中显式保存的功能开关名，不读取或输出其值。"""
    path = settings_path()
    if not path.is_file():
        return []
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("features"), dict):
        raise ValueError(f"settings file is invalid: {path}")
    keys = data["features"].keys()
    if not all(isinstance(key, str) for key in keys):
        raise ValueError("settings file feature keys must be strings")
    return sorted(keys)


def configured_environment_variables() -> list[str]:
    """返回当前进程中已设置的 Wttch 相关环境变量名。"""
    return [
        name
        for name in CONFIGURATION_ENVIRONMENT_VARIABLES
        if os.environ.get(name, "").strip()
    ]


def report(working_directory: Path | None = None) -> dict[str, list[str]]:
    """生成可安全展示的配置索引；结果只包含字段和变量名称。"""
    return {
        "working_directory_config_fields": configured_fields(working_directory),
        "environment_variables": configured_environment_variables(),
        "plugin_setting_overrides": setting_overrides(),
    }


def main() -> int:
    """将配置索引以 JSON 输出，供 plugin-info Skill 直接展示。"""
    print(json.dumps(report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
