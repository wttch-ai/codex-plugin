#!/usr/bin/env python3
"""Shared entry point for all Python-backed skills in the Wttch plugin."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


def load_policy(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("gate policy must be a YAML object")
    if data.get("version") != 1:
        raise ValueError("gate policy version must be 1")
    defaults = data.get("defaults")
    rules = data.get("rules")
    if not isinstance(defaults, dict) or not isinstance(rules, list):
        raise ValueError("gate policy requires defaults and rules")
    if defaults.get("action") not in {"allow", "deny", "review"}:
        raise ValueError("defaults.action must be allow, deny, or review")
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"rules[{index}] must be an object")
        if rule.get("action") not in {"allow", "deny", "review"}:
            raise ValueError(f"rules[{index}].action must be allow, deny, or review")
        for pattern in rule.get("input_regex", []):
            re.compile(pattern)
    return data


def input_text(event: dict[str, Any]) -> str:
    value = event.get("tool_input", {})
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        return value["command"]
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def matching_rule(policy: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    tool = str(event.get("tool_name", ""))
    text = input_text(event)
    for rule in policy["rules"]:
        tools = rule.get("tools", [])
        if tools and tool not in tools:
            continue
        patterns = rule.get("input_regex", [])
        if patterns and not any(re.search(pattern, text) for pattern in patterns):
            continue
        return rule
    return {
        "id": "defaults",
        "action": policy["defaults"]["action"],
        "reason": "No explicit gate rule matched.",
    }


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def allow(context: str | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    }
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def openrouter_review(rule: dict[str, Any], event: dict[str, Any]) -> tuple[bool, str]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("JEV_OPENROUTER_MODEL", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    if not model:
        raise RuntimeError("JEV_OPENROUTER_MODEL is not set")

    base_url = os.environ.get(
        "JEV_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    timeout = float(os.environ.get("JEV_OPENROUTER_TIMEOUT", "20"))
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are JEV, a conservative tool-call policy judge. "
                        "Return one JSON object with keys decision (allow or deny) "
                        "and reason. Do not return markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "policy_instruction": rule.get(
                                "instruction", "Review the action safely."
                            ),
                            "tool_name": event.get("tool_name"),
                            "tool_input": event.get("tool_input"),
                            "cwd": event.get("cwd"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://chatgpt.com/",
            "X-Title": "Wttch JEV Gate",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter returned HTTP {exc.code}: {detail}") from exc

    content = payload["choices"][0]["message"]["content"]
    result = json.loads(content)
    decision = str(result.get("decision", "")).lower()
    reason = str(result.get("reason", "JEV returned no reason."))
    if decision not in {"allow", "deny"}:
        raise RuntimeError("JEV decision must be allow or deny")
    return decision == "allow", reason


def evaluate(policy: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    rule = matching_rule(policy, event)
    action = rule["action"]
    if action == "allow":
        return allow()
    if action == "deny":
        return deny(str(rule.get("reason", f"Denied by gate rule {rule['id']}.")))
    try:
        approved, reason = openrouter_review(rule, event)
    except Exception as exc:
        if bool(policy["defaults"].get("fail_open", False)):
            return allow(f"JEV review was unavailable; fail-open applied: {exc}")
        return deny(f"JEV review failed closed: {exc}")
    return allow(f"JEV allowed this action: {reason}") if approved else deny(reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("jev-gate", "validate-jev-policy"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()

    try:
        policy = load_policy(args.policy)
        if args.command == "validate-jev-policy":
            print(json.dumps({"ok": True, "rules": len(policy["rules"])}))
            return 0
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        print(json.dumps(evaluate(policy, event), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(deny(f"JEV gate runtime error: {exc}"), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
