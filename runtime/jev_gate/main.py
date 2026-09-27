#!/usr/bin/env python3
"""JEV 策略校验和 PreToolUse 入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gate import evaluate
from .policy import load_policy


def main() -> int:
    """分派策略校验命令或实际的 PreToolUse Hook 评估。

    两个子命令共用相同的策略加载和验证路径，确保离线校验通过的策略与 Hook 实际
    使用的策略结构一致。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("jev-gate", "validate-jev-policy"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    policy = load_policy(args.policy)

    if args.command == "validate-jev-policy":
        # 该命令不读取标准输入，方便在发布或编辑策略时单独验证 YAML。
        print(json.dumps({"ok": True, "rules": len(policy["rules"])}))
        return 0

    # Codex 通过标准输入传入本次工具调用的完整 Hook 事件。
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise ValueError("hook input must be a JSON object")
    print(json.dumps(evaluate(policy, event), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
