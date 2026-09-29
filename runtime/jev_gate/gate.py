#!/usr/bin/env python3
"""根据 JEV 策略评估一个 PreToolUse 事件。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .policy import matching_rule
from .review import review
from settings import audit_log_path, load_settings
# 统一日志与可选的旧审计日志并行写入，兼容已有 audit_log 设置。
from operation_log import record as record_operation


def deny(reason: str) -> dict[str, Any]:
    """构造 Codex PreToolUse 协议中的拒绝响应。"""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def allow(context: str | None = None) -> dict[str, Any]:
    """Construct a non-blocking response, optionally with model-visible context."""
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
    }
    if context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def record_audit(
    event: dict[str, Any], rule: dict[str, Any], result: dict[str, Any]
) -> None:
    """将一次已评估的决策追加为 JSONL 记录，且不写入完整工具输入或密钥。"""
    output = result["hookSpecificOutput"]
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": event.get("tool_name"),
        "rule_id": rule.get("id", "unknown"),
        "policy_action": rule.get("action"),
        "decision": output.get("permissionDecision", "allow"),
        "reason": output.get("permissionDecisionReason")
        or output.get("additionalContext"),
    }
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSONL 每行一条记录，追加写入便于流式读取和故障后的部分恢复。
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def evaluate(policy: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """将事件映射为最终的 PreToolUse 决策，并按需留下审计记录。

    ``review`` 规则依赖远程模型。远程审查关闭、失败或返回拒绝时的行为由本机设置
    及策略的 ``fail_open`` 决定，保证所有分支都形成明确的 allow 或 deny 响应。
    """
    cwd = event.get("cwd")
    working_directory = Path(cwd) if isinstance(cwd, str) and cwd.strip() else None
    settings, _ = load_settings(working_directory)
    if not settings["jev_gate"]:
        # 总开关关闭后不匹配规则、不访问远程服务，也不记录审计日志。
        return allow()
    rule = matching_rule(policy, event)
    action = rule["action"]
    if action == "allow":
        result = allow()
    elif action == "deny":
        reason = str(rule.get("reason", f"Gate 规则 {rule['id']} 已拒绝该操作。"))
        result = deny(reason if settings["show_decision_reason"] else "JEV Gate 已拒绝该操作。")
    elif not settings["openrouter_review"]:
        # review 不能在本机关闭时被静默放行，保持默认的失败关闭语义。
        result = deny(
            "OpenRouter 审查已关闭。"
            if settings["show_decision_reason"]
            else "JEV Gate 已拒绝该操作。"
        )
    else:
        try:
            approved, reason = review(rule, event)
        except Exception as exc:
            # 网络、认证和模型返回格式错误都会进入这里，由策略明确选择失败语义。
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
        # 审计仅记录决策元数据，不保存可能包含敏感数据的完整工具参数。
        record_audit(event, rule, result)
    # 仅保存工具名、规则和决策，不保存完整工具参数或远程审查上下文。
    record_operation("jev_gate", details={
        "tool_name": event.get("tool_name"),
        "rule_id": rule.get("id", "unknown"),
        "decision": result["hookSpecificOutput"].get("permissionDecision", "allow"),
    })
    return result
