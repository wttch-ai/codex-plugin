#!/usr/bin/env python3
"""Unified CLI for JEV decisions, Hooks, and Gate policy validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Support both ``python runtime/jev/main.py`` and package imports in tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev.decision import list_decisions, run_named_decision, run_user_prompt_submit_hook
from jev.gate import evaluate
from jev.policy import load_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    decision = commands.add_parser("decision", help="发现或执行 JEV 决策。")
    decision_commands = decision.add_subparsers(dest="decision_command", required=True)
    decision_commands.add_parser("list", help="列出内置和项目级决策。")
    decision_run = decision_commands.add_parser("run", help="执行指定决策。")
    decision_run.add_argument("name")

    hook = commands.add_parser("hook", help="执行 Codex Hook。")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    hook_commands.add_parser("user-prompt-submit", help="执行 UserPromptSubmit 决策。")
    pre_tool_use = hook_commands.add_parser("pre-tool-use", help="执行 PreToolUse Gate。")
    pre_tool_use.add_argument("--policy", type=Path, required=True)

    policy = commands.add_parser("policy", help="维护 Gate 策略。")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    validate = policy_commands.add_parser("validate", help="校验 Gate 策略。")
    validate.add_argument("--policy", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "decision":
        if args.decision_command == "list":
            return list_decisions()
        return run_named_decision(args.name)

    if args.command == "policy":
        policy = load_policy(args.policy)
        print(json.dumps({"ok": True, "rules": len(policy["rules"])}))
        return 0

    if args.hook_command == "user-prompt-submit":
        return run_user_prompt_submit_hook()

    policy = load_policy(args.policy)
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise ValueError("hook input must be a JSON object")
    print(json.dumps(evaluate(policy, event), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
