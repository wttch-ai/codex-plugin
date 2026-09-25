#!/usr/bin/env python3
"""处理 UserPromptSubmit 事件中的模型限制。"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from settings import load_settings


def normalize_model(value: str) -> str:
    normalized = re.sub(r"[-_\s]+", "-", value.strip().lower())
    return re.sub(r"^gpt(?=\d)", "gpt-", normalized)


def block(reason: str) -> dict[str, str]:
    return {"decision": "block", "reason": reason}


def warn(reason: str) -> dict[str, Any]:
    return {
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": reason,
        },
    }


def handle_blocked_model(model: str, action: str) -> dict[str, Any]:
    if action == "warn":
        return warn(f"警告：当前模型 {model} 在模型 Gate 禁用清单中，但本轮请求将继续。")
    if action == "ask":
        return block(
            f"当前模型 {model} 在模型 Gate 禁用清单中。"
            "请确认是否继续，或切换到允许的模型后重新发送请求。"
        )
    return block(f"模型 Gate 已阻止当前模型：{model}。")


def evaluate(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    if not settings["model_gate"]:
        return None
    model = event.get("model")
    if not isinstance(model, str) or not model.strip():
        return block("模型 Gate 无法确定当前模型，本轮请求已停止。")
    blocked = {normalize_model(item) for item in settings["blocked_models"]}
    if normalize_model(model) not in blocked:
        return None
    return handle_blocked_model(model, settings["model_gate_action"])


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        settings, _ = load_settings()
        result = evaluate(event, settings)
    except Exception as exc:
        result = block(f"模型 Gate 运行失败，本轮请求已停止：{exc}")
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
