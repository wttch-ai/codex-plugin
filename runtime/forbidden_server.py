#!/usr/bin/env python3
"""根据项目规则对 PreToolUse 工具目标执行 block 或 warn。

规则从工具调用工作目录向父目录查找最近的
``.agents/wttch/forbidden-server.yml``。匹配只在内存中检查序列化后的 ``tool_input``，
完整工具参数不会写入日志；日志只记录工具名和最终决定。多个规则同时命中时 block
优先，配置或 JSON 错误则返回非阻断警告，方便用户修复项目配置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from notice import hook_notice
from wttch_logging import record_operation


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
    """加载并规范化离工具调用工作目录最近的 forbidden-server 规则。"""
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
    """把命中规则转换为符合 PreToolUse 协议的阻止或警告响应。"""
    message = hook_notice(
        f"forbidden-server 命中 {rule['target']}（{rule['description']}），规则为 {action}。"
    )
    if action == "block":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}
    # A PreToolUse hook continues by omitting permissionDecision.  Codex only
    # accepts an explicit "allow" when it accompanies an updatedInput rewrite.
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}


def evaluate(event: dict[str, Any]) -> dict[str, Any]:
    """匹配工具输入，并让 block 在同时命中多条规则时优先。"""
    text = event_text(event)
    matches = [rule for rule in load_rules(event) if rule["target"] in text]
    if not matches:
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    # A block always takes precedence when one call matches multiple rules.
    matched = next((rule for rule in matches if rule["action"] == "block"), matches[0])
    return response(matched["action"], matched)


def main() -> int:
    """处理一个 PreToolUse JSON 事件，并只向 stdout 写协议响应。"""
    try:
        event = json.load(sys.stdin)
        result = evaluate(event)
        output = result["hookSpecificOutput"]
        # warn/allow 都不带 permissionDecision，需要由响应形态还原日志决策。
        decision = output.get("permissionDecision")
        if decision is None:
            decision = "warn" if "additionalContext" in output else "allow"
        record_operation(
            "forbidden_server",
            details={"tool_name": event.get("tool_name"), "decision": decision},
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        record_operation("forbidden_server", result="error")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": hook_notice(f"forbidden-server 未执行：{exc}")}}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
