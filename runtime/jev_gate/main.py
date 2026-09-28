#!/usr/bin/env python3
"""JEV 策略校验和 PreToolUse 入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gate import evaluate
from .policy import load_policy


DECISION_ROOT = Path(".agents") / "wttch" / "jev"


def decision_files(cwd: Path) -> list[Path]:
    """返回当前项目中的 JEV 决策文件。"""
    return sorted((cwd / DECISION_ROOT).glob("*.yml"))


def resolve_decision(name: str, cwd: Path) -> Path:
    """按文件名或决策名解析项目决策文件。"""
    candidate = Path(name)
    if candidate.is_file():
        return candidate.resolve()
    for path in decision_files(cwd):
        if path.stem == name or path.name == name:
            return path.resolve()
    raise FileNotFoundError(f"JEV 决策不存在：{name}")


def list_decisions(cwd: Path) -> int:
    """列出当前项目可执行的 JEV 决策。"""
    entries = []
    for path in decision_files(cwd):
        policy = load_policy(path)
        actions = sorted({rule["action"] for rule in policy["rules"]})
        entries.append({
            "name": path.stem,
            "file": str(path),
            "type": policy["type"],
            "actions": actions,
        })
    print(json.dumps({"directory": str(cwd / DECISION_ROOT), "decisions": entries}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    """分派策略校验命令或实际的 PreToolUse Hook 评估。

    两个子命令共用相同的策略加载和验证路径，确保离线校验通过的策略与 Hook 实际
    使用的策略结构一致。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("jev-decision", "jev-gate", "validate-jev-policy"):
        sub = subparsers.add_parser(command)
        if command == "jev-decision":
            decision = sub.add_subparsers(dest="decision_command", required=True)
            decision.add_parser("list")
            run = decision.add_parser("run")
            run.add_argument("name")
            run.add_argument("--cwd", type=Path, default=Path.cwd())
        else:
            sub.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "jev-decision":
        if args.decision_command == "list":
            return list_decisions(Path.cwd())
        policy = load_policy(resolve_decision(args.name, args.cwd))
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("Hook 输入必须是 JSON 对象")
        print(json.dumps(evaluate(policy, event), ensure_ascii=False))
        return 0

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
