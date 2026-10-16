#!/usr/bin/env python3
"""显示 Wttch 插件当前已配置的项目，不显示任何配置值。"""

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
