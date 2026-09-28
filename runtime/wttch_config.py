#!/usr/bin/env python3
"""加载仅供 Wttch 插件运行时使用的工作目录配置。"""

from __future__ import annotations

from pathlib import Path

import yaml


CONFIG_PATH = Path(".agents") / "wttch" / "config.yml"


def load_config(working_directory: Path | None = None) -> dict[str, object]:
    """加载工作目录配置并验证其顶层结构，但不输出任何配置值。"""
    path = (working_directory or Path.cwd()) / CONFIG_PATH
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Wttch config must be a YAML object: {path}")
    return data


def configured_fields(working_directory: Path | None = None) -> list[str]:
    """返回配置文件中存在的叶子字段路径，不返回对应值。"""
    fields: list[str] = []

    def collect(value: object, prefix: str) -> None:
        if isinstance(value, dict):
            for key, nested_value in value.items():
                # YAML 键必须是字符串，才能稳定地展示为可识别的配置路径。
                if not isinstance(key, str):
                    raise ValueError(".agents/wttch/config.yml keys must be strings")
                collect(nested_value, f"{prefix}.{key}" if prefix else key)
        else:
            fields.append(prefix)

    collect(load_config(working_directory), "")
    return fields


def openrouter_api_key(working_directory: Path | None = None) -> str:
    """从指定项目的 ``.agents/wttch/config.yml`` 读取 ``openrouter.api_key``。

    未指定目录时使用当前进程工作目录，因此本插件的普通 Skill 运行时脚本可以直接
    调用此函数。该模块位于插件共享 runtime 中，其他插件不会自动加载或读取此文件。
    配置文件不存在或字段为空时返回空字符串；无效结构会抛出明确错误。
    """
    data = load_config(working_directory)
    openrouter = data.get("openrouter", {})
    if not isinstance(openrouter, dict):
        raise ValueError(".agents/wttch/config.yml openrouter must be an object")
    api_key = openrouter.get("api_key", "")
    if not isinstance(api_key, str):
        raise ValueError(".agents/wttch/config.yml openrouter.api_key must be a string")
    return api_key.strip()
