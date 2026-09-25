#!/usr/bin/env python3
"""根据 JEV 策略评估一个 PreToolUse 事件。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from .policy import matching_rule
from .review import review
from settings import audit_log_path, load_settings


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


def record_audit(
    event: dict[str, Any], rule: dict[str, Any], result: dict[str, Any]
) -> None:
    output = result["hookSpecificOutput"]
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": event.get("tool_name"),
        "rule_id": rule.get("id", "unknown"),
        "policy_action": rule.get("action"),
        "decision": output.get("permissionDecision"),
        "reason": output.get("permissionDecisionReason")
        or output.get("additionalContext"),
    }
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def evaluate(policy: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    settings, _ = load_settings()
    if not settings["jev_gate"]:
        return allow()
    rule = matching_rule(policy, event)
    action = rule["action"]
    if action == "allow":
        result = allow()
    elif action == "deny":
        reason = str(rule.get("reason", f"Gate 规则 {rule['id']} 已拒绝该操作。"))
        result = deny(reason if settings["show_decision_reason"] else "JEV Gate 已拒绝该操作。")
    elif not settings["openrouter_review"]:
        result = deny(
            "OpenRouter 审查已关闭。"
            if settings["show_decision_reason"]
            else "JEV Gate 已拒绝该操作。"
        )
    else:
        try:
            approved, reason = review(rule, event)
        except Exception as exc:
            if bool(policy["defaults"].get("fail_open", False)):
                detail = f"JEV 审查不可用，已应用失败放行策略：{exc}"
                result = allow(detail if settings["show_decision_reason"] else None)
            else:
                detail = f"JEV 审查失败，已应用失败关闭策略：{exc}"
                result = deny(
                    detail
                    if settings["show_decision_reason"]
                    else "JEV Gate 已拒绝该操作。"
                )
        else:
            if approved:
                detail = f"JEV 已允许该操作：{reason}"
                result = allow(detail if settings["show_decision_reason"] else None)
            else:
                result = deny(
                    reason
                    if settings["show_decision_reason"]
                    else "JEV Gate 已拒绝该操作。"
                )
    if settings["audit_log"]:
        record_audit(event, rule, result)
    return result
