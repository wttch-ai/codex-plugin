#!/usr/bin/env python3
"""加载并匹配 JEV YAML 策略。"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import yaml


def load_policy(path: Path) -> dict[str, Any]:
    """加载 YAML 策略并校验 Gate 运行前必须成立的结构约束。

    正则在这里预编译一次，以便在 Hook 真正执行前暴露语法错误，而不是在匹配到某条
    规则时才失败。
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("gate policy must be a YAML object")
    if data.get("version") != 1:
        raise ValueError("gate policy version must be 1")
    if data.get("type") not in {"choice", "noul", "score"}:
        raise ValueError("JEV 决策类型必须是 choice、noul 或 score")
    if "group" in data and data["group"] is not None and not isinstance(data["group"], str):
        raise ValueError("JEV 决策 group 必须是字符串或空值")
    if not isinstance(data.get("question"), str) or not data["question"].strip():
        raise ValueError("JEV 决策必须包含 question")
    if not isinstance(data.get("system_prompt"), str) or not data["system_prompt"].strip():
        raise ValueError("JEV 决策必须包含 system_prompt")
    if data["type"] == "choice":
        options = data.get("options")
        if not isinstance(options, list) or len(options) < 2 or not all(
            isinstance(item, dict) and isinstance(item.get("name"), str)
            and isinstance(item.get("prompt"), str) for item in options
        ):
            raise ValueError("choice 决策的 options 必须包含至少两个 name/prompt 对象")
    elif data["type"] == "noul":
        outcomes = data.get("outcomes")
        if not isinstance(outcomes, dict) or not all(
            isinstance(outcomes.get(key), str) and outcomes[key].strip()
            for key in ("true", "false")
        ):
            raise ValueError("noul 决策必须包含 true/false 的 outcomes 提示词")
    else:
        levels = data.get("levels")
        if not isinstance(levels, list) or len(levels) < 2 or not all(
            isinstance(item, dict) and isinstance(item.get("name"), str)
            and isinstance(item.get("prompt"), str) for item in levels
        ):
            raise ValueError("score 决策的 levels 必须包含至少两个 name/prompt 对象")
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
            # 仅用于验证可编译性；运行时仍按原字符串调用 re.search。
            re.compile(pattern)
    return data


def input_text(event: dict[str, Any]) -> str:
    """提取用于正则匹配的工具输入文本。

    Bash 命令是最常见且最适合直接匹配的形式；其他工具输入统一序列化为稳定 JSON，
    使策略也能按参数内容匹配 Edit、Write 等结构化调用。
    """
    value = event.get("tool_input", {})
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        return value["command"]
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def matching_rule(policy: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """按配置顺序返回第一条同时匹配工具和输入的规则。

    空 ``tools`` 或 ``input_regex`` 分别代表不限制工具、或不限制输入；两者均为空的
    规则会匹配所有事件，因此应由策略作者将其放在具体规则之后。
    """
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
    # 没有显式命中时把 defaults 伪装成规则，使后续评估和审计使用统一数据结构。
    return {
        "id": "defaults",
        "action": policy["defaults"]["action"],
        "reason": "没有匹配到明确的 Gate 规则。",
    }
