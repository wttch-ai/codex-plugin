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
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("jev-gate", "validate-jev-policy"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    policy = load_policy(args.policy)

    if args.command == "validate-jev-policy":
        print(json.dumps({"ok": True, "rules": len(policy["rules"])}))
        return 0

    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise ValueError("hook input must be a JSON object")
    print(json.dumps(evaluate(policy, event), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
