#!/usr/bin/env python3
"""Shared entry point for all Python-backed skills in the Wttch plugin."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FEATURE_CATALOG_PATH = PLUGIN_ROOT / "config" / "features.json"


def settings_path() -> Path:
    override = os.environ.get("WTTCH_PLUGIN_SETTINGS_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "wttch-codex-plugin" / "settings.json"


def audit_log_path() -> Path:
    override = os.environ.get("WTTCH_PLUGIN_AUDIT_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "wttch-codex-plugin" / "audit.jsonl"


def valid_default(entry: dict[str, Any]) -> bool:
    feature_type = entry.get("type")
    default = entry.get("default")
    if feature_type == "boolean":
        return isinstance(default, bool)
    if feature_type == "string_list":
        return isinstance(default, list) and all(isinstance(item, str) for item in default)
    return False


def load_feature_catalog(path: Path = FEATURE_CATALOG_PATH) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("feature catalog version must be 1")
    entries = data.get("features")
    if not isinstance(entries, list):
        raise ValueError("feature catalog requires a features array")
    catalog: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"features[{index}] must be an object")
        key = entry.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError(f"features[{index}].key is invalid")
        if key in catalog:
            raise ValueError(f"duplicate feature key: {key}")
        if not valid_default(entry):
            raise ValueError(f"feature {key} has an unsupported type or invalid default")
        if not isinstance(entry.get("label"), str) or not isinstance(
            entry.get("description"), str
        ):
            raise ValueError(f"feature {key} requires label and description")
        catalog[key] = entry
    return catalog


def clone_default(value: Any) -> Any:
    return list(value) if isinstance(value, list) else value


def valid_value(entry: dict[str, Any], value: Any) -> bool:
    if entry["type"] == "boolean":
        return isinstance(value, bool)
    if entry["type"] == "string_list":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def load_settings() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    catalog = load_feature_catalog()
    values = {key: clone_default(entry["default"]) for key, entry in catalog.items()}
    path = settings_path()
    if not path.exists():
        return values, catalog
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("features", {}), dict):
        raise ValueError(f"settings file is invalid: {path}")
    for key, value in data["features"].items():
        if key not in catalog:
            raise ValueError(f"unknown feature in settings file: {key}")
        if not valid_value(catalog[key], value):
            raise ValueError(f"feature {key} has an invalid value")
        values[key] = value
    return values, catalog


def write_settings(values: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "features": values}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "on", "yes", "1", "enable", "enabled"}:
        return True
    if normalized in {"false", "off", "no", "0", "disable", "disabled"}:
        return False
    raise ValueError("value must be on/off or true/false")


def parse_setting_value(entry: dict[str, Any], value: str) -> Any:
    if entry["type"] == "boolean":
        return parse_boolean(value)
    if entry["type"] == "string_list":
        stripped = value.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not valid_value(entry, parsed):
                raise ValueError("value must be a JSON array of strings")
            return parsed
        return [item.strip() for item in stripped.split(",") if item.strip()]
    raise ValueError(f"unsupported setting type: {entry['type']}")


def normalize_model(value: str) -> str:
    normalized = re.sub(r"[-_\s]+", "-", value.strip().lower())
    return re.sub(r"^gpt(?=\d)", "gpt-", normalized)


def model_gate(event: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
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
    reason = str(result.get("reason", "JEV 未返回原因。"))
    if decision not in {"allow", "deny"}:
        raise RuntimeError("JEV decision must be allow or deny")
    return decision == "allow", reason


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
            approved, reason = openrouter_review(rule, event)
        except Exception as exc:
            if bool(policy["defaults"].get("fail_open", False)):
                detail = f"JEV 审查不可用，已应用失败放行策略：{exc}"
                result = allow(detail if settings["show_decision_reason"] else None)
            else:
                detail = f"JEV 审查失败，已应用失败关闭策略：{exc}"
                result = deny(detail if settings["show_decision_reason"] else "JEV Gate 已拒绝该操作。")
        else:
            if approved:
                detail = f"JEV 已允许该操作：{reason}"
                result = allow(detail if settings["show_decision_reason"] else None)
            else:
                result = deny(reason if settings["show_decision_reason"] else "JEV Gate 已拒绝该操作。")
    if settings["audit_log"]:
        record_audit(event, rule, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("jev-gate", "validate-jev-policy"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--policy", type=Path, required=True)
    subparsers.add_parser("list-settings")
    set_parser = subparsers.add_parser("set-setting")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    subparsers.add_parser("reset-settings")
    subparsers.add_parser("model-gate")
    args = parser.parse_args()

    try:
        if args.command == "list-settings":
            values, catalog = load_settings()
            print(
                json.dumps(
                    {
                        "settings_file": str(settings_path()),
                        "features": [
                            {**entry, "value": values[key]}
                            for key, entry in catalog.items()
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "set-setting":
            values, catalog = load_settings()
            if args.key not in catalog:
                raise ValueError(f"unknown feature: {args.key}")
            values[args.key] = parse_setting_value(catalog[args.key], args.value)
            write_settings(values)
            print(json.dumps({"ok": True, "key": args.key, "value": values[args.key]}))
            return 0
        if args.command == "reset-settings":
            catalog = load_feature_catalog()
            values = {
                key: clone_default(entry["default"]) for key, entry in catalog.items()
            }
            write_settings(values)
            print(json.dumps({"ok": True, "features": values}, ensure_ascii=False))
            return 0
        if args.command == "model-gate":
            event = json.load(sys.stdin)
            if not isinstance(event, dict):
                raise ValueError("hook input must be a JSON object")
            settings, _ = load_settings()
            result = model_gate(event, settings)
            if result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
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
        if args.command == "model-gate":
            print(
                json.dumps(
                    {
                        "continue": False,
                        "stopReason": f"模型 Gate 运行错误：{exc}",
                        "systemMessage": "由于模型 Gate 运行失败，本轮请求已停止。",
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        print(json.dumps(deny(f"JEV Gate 运行错误：{exc}"), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
