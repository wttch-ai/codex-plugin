#!/usr/bin/env python3
"""处理 UserPromptSubmit 事件中的模型限制。"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from settings import load_settings
# 模型 Gate 记录最终决策，便于查询被阻止、警告或放行的请求数量。
from operation_log import record as record_operation


def normalize_model(value: str) -> str:
    """将模型标识归一化，保证配置中的常见写法可以等价匹配。

    模型名来自 Hook 事件和用户本机配置，两端可能分别使用空格、下划线或连字符，
    例如 ``GPT_6 SOL`` 与 ``gpt-6-sol``。同时为 ``gpt6`` 这种缺少分隔符的
    写法补上连字符，避免因格式差异绕过禁用清单。
    """
    normalized = re.sub(r"[-_\s]+", "-", value.strip().lower())
    return re.sub(r"^gpt(?=\d)", "gpt-", normalized)


def block(reason: str) -> dict[str, str]:
    """构造 UserPromptSubmit 约定的阻止响应。"""
    return {"decision": "block", "reason": reason}


def warn(reason: str) -> dict[str, Any]:
    """构造继续本轮请求、但向用户和后续上下文注入警告的响应。"""
    return {
        "systemMessage": reason,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": reason,
        },
    }


def handle_blocked_model(model: str, action: str) -> dict[str, Any]:
    """依照配置的处理方式处理命中禁用清单的模型。"""
    if action == "warn":
        return warn(f"警告：当前模型 {model} 在模型 Gate 禁用清单中，但本轮请求将继续。")
    return block(
        f"模型 Gate 已阻止当前模型：{model}。"
        "如需关闭此限制，请运行："
        "python3 runtime/settings.py set-setting model_gate off"
    )


def evaluate(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    """评估当前事件；返回 ``None`` 表示 Hook 无需输出且请求可继续。

    无法从事件中可靠取到模型时采用失败关闭策略，防止模型 Gate 在事件格式变化时
    被静默绕过。
    """
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
    """从标准输入读取 Hook 事件，并仅在需要干预时输出 JSON 响应。"""
    try:
        # Codex 通过标准输入传入单个 JSON 对象，标准输出只能保留 Hook 协议响应。
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        settings, _ = load_settings()
        result = evaluate(event, settings)
    except Exception as exc:
        # Hook 自身异常也必须阻止请求，避免配置或解析错误失去保护作用。
        result = block(f"模型 Gate 运行失败，本轮请求已停止：{exc}")
        # 异常分支统一记为 error，但仍输出原有失败关闭响应。
        record_operation("model_gate", result="error")
    else:
        # result 为 None 代表没有命中限制，在日志中明确记为 allow。
        record_operation("model_gate", details={"decision": result.get("decision", "allow") if result else "allow"})
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
