#!/usr/bin/env python3
"""作为 SessionStart Hook 的环境预热目标。"""

from __future__ import annotations


def main() -> int:
    """环境已由 bootstrap 准备完成，无需再输出 Hook 响应。"""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
