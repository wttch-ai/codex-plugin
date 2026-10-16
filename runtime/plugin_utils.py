#!/usr/bin/env python3
"""为 plugin-utils Skill 提供不泄密的项目配置索引。

本入口只返回当前项目配置中出现的字段路径，不返回字段值、默认值或推断值，尤其不会
显示 OpenRouter API Key。运行时、日志状态和环境维护由统一 runner 负责，本文件只承担
配置结构发现，避免辅助 Skill 意外读取敏感内容。
"""

from __future__ import annotations

import json
from pathlib import Path
from wttch_config import configured_fields


def report(working_directory: Path | None = None) -> dict[str, list[str]]:
    """生成可安全展示的配置索引；结果只包含字段和变量名称。"""
    return {
        "working_directory_config_fields": configured_fields(working_directory),
    }


def main() -> int:
    """将配置索引以 JSON 输出，供 plugin-utils Skill 直接展示。"""
    print(json.dumps(report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
