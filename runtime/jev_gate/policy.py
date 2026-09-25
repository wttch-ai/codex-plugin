#!/usr/bin/env python3
"""加载并匹配 JEV YAML 策略。"""

from __future__ import annotations

import json
from pathlib import Path
import re
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
        "reason": "没有匹配到明确的 Gate 规则。",
    }
