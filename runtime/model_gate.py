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


def evaluate(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    if not settings["model_gate"]:
        return None
    model = event.get("model")
    if not isinstance(model, str) or not model.strip():
        return {
            "continue": False,
            "stopReason": "模型 Gate 无法确定当前模型。",
            "systemMessage": "由于无法获取当前模型，本轮请求已停止。",
        }
    blocked = {normalize_model(item) for item in settings["blocked_models"]}
    if normalize_model(model) not in blocked:
        return None
    reason = f"模型 Gate 已阻止当前模型：{model}。"
    return {"continue": False, "stopReason": reason, "systemMessage": reason}


def main() -> int:
    event = json.load(sys.stdin)
    if not isinstance(event, dict):
        raise ValueError("hook input must be a JSON object")
    settings, _ = load_settings()
    result = evaluate(event, settings)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
