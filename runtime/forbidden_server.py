#!/usr/bin/env python3
"""Block or warn on project-configured forbidden tool-call targets."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml


CONFIG_RELATIVE_PATH = Path(".agents") / "wttch" / "forbidden-server.yml"
VALID_ACTIONS = {"block", "warn"}


def config_path(event: dict[str, Any]) -> Path | None:
    """Find the closest project configuration from the tool call's cwd."""
    start = Path(str(event.get("cwd") or Path.cwd())).resolve()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    return None


def load_rules(event: dict[str, Any]) -> list[dict[str, str]]:
    path = config_path(event)
    if path is None:
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or []
    if not isinstance(payload, list):
        raise ValueError(f"{path} 必须是规则列表")
    rules: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"{path} 每项必须是对象")
        target = str(item.get("target") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        description = str(item.get("description") or target).strip()
        if not target or action not in VALID_ACTIONS:
            raise ValueError(f"{path} 每项必须含非空 target，以及 block 或 warn action")
        rules.append({"target": target, "action": action, "description": description})
    return rules


def event_text(event: dict[str, Any]) -> str:
    """Serialize tool input only for local target matching; never log it."""
    return json.dumps(event.get("tool_input") or {}, ensure_ascii=False, default=str)


def response(action: str, rule: dict[str, str]) -> dict[str, Any]:
    message = f"forbidden-server: 命中 {rule['target']}（{rule['description']}），规则为 {action}。"
    if action == "block":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}
    # A PreToolUse hook continues by omitting permissionDecision.  Codex only
    # accepts an explicit "allow" when it accompanies an updatedInput rewrite.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}


def evaluate(event: dict[str, Any]) -> dict[str, Any]:
    text = event_text(event)
    matches = [rule for rule in load_rules(event) if rule["target"] in text]
    if not matches:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    # A block always takes precedence when one call matches multiple rules.
    matched = next((rule for rule in matches if rule["action"] == "block"), matches[0])
    return response(matched["action"], matched)


def main() -> int:
    try:
        event = json.load(sys.stdin)
        print(json.dumps(evaluate(event), ensure_ascii=False))
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": f"forbidden-server 未执行：{exc}"}}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
