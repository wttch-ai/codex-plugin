#!/usr/bin/env python3
"""执行项目级 JEV UserPromptSubmit 决策，并在 YAML 指定的条件下要求用户确认。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jev.main import decision_files, load_decision, request_decision
from operation_log import record as record_operation
from settings import load_settings


def block(reason: str) -> dict[str, str]:
    return {"decision": "block", "reason": reason}


def input_text(event: dict[str, Any]) -> str:
    for key in ("prompt", "user_input", "message"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError("UserPromptSubmit 事件缺少用户输入")


def project_hook_decisions(cwd: Path) -> list[dict[str, Any]]:
    """仅加载当前项目声明 Hook 的决策，绝不自动执行插件内置示例。"""
    result: list[dict[str, Any]] = []
    for path in decision_files(cwd):
        if path.parent.name == "decisions":
            continue
        definition = load_decision(path)
        hook = definition.get("hook")
        if isinstance(hook, dict) and hook.get("event") == "UserPromptSubmit":
            result.append(definition)
    return result


def answer_for(payload: dict[str, Any], name: str) -> dict[str, Any]:
    for key in ("answers", "results"):
        container = payload.get(key)
        if isinstance(container, dict) and isinstance(container.get(name), dict):
            return container[name]
    answer = payload.get(name)
    if isinstance(answer, dict):
        return answer
    raise ValueError(f"JEV 响应缺少 {name} 的结构化答案")


def numeric(answer: dict[str, Any], field: str, question: str) -> float:
    # Jev 的原生响应：choice 的概率在 probabilities[choice]，noul 的概率在 noul；
    # score 直接返回 score。保留同名字段兼容自定义代理返回值。
    value = answer.get(field)
    if field == "probability" and value is None:
        answer_type = answer.get("type")
        if answer_type == "noul":
            value = answer.get("noul")
        elif answer_type == "choice":
            probabilities = answer.get("probabilities")
            choice = answer.get("choice")
            if isinstance(probabilities, dict) and isinstance(choice, str):
                value = probabilities.get(choice)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"JEV 响应的 {question}.{field} 必须是数字")
    return float(value)


def review_reasons(definition: dict[str, Any], answers: dict[str, dict[str, Any]]) -> list[str]:
    hook = definition["hook"]
    conditions = hook.get("review_when", {})
    if not isinstance(conditions, dict):
        raise ValueError("hook.review_when 必须是对象")
    reasons: list[str] = []
    for question, condition in conditions.items():
        if question not in answers or not isinstance(condition, dict):
            raise ValueError(f"hook.review_when.{question} 无效")
        for rule, limit in condition.items():
            if rule.endswith("_below"):
                field = rule.removesuffix("_below")
                if numeric(answers[question], field, question) < float(limit):
                    reasons.append(f"{question}.{field} 低于 {limit}")
            elif rule.endswith("_between"):
                field = rule.removesuffix("_between")
                if not isinstance(limit, list) or len(limit) != 2:
                    raise ValueError(f"hook.review_when.{question}.{rule} 必须是两个数字的数组")
                current = numeric(answers[question], field, question)
                if float(limit[0]) <= current <= float(limit[1]):
                    reasons.append(f"{question}.{field} 处于 {limit[0]}–{limit[1]}")
            else:
                raise ValueError(f"不支持的 Hook 复核规则：{rule}")
    return reasons


def confirmed(text: str, hook: dict[str, Any]) -> str | None:
    confirmation = hook.get("confirmation")
    if not isinstance(confirmation, dict):
        return None
    pattern = confirmation.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("hook.confirmation.pattern 必须是非空字符串")
    match = re.match(pattern, text)
    if not match:
        return None
    context = confirmation.get("context")
    if not isinstance(context, str) or not context:
        raise ValueError("hook.confirmation.context 必须是非空字符串")
    return context.format(*match.groups(), **match.groupdict())


def evaluate_definition(
    definition: dict[str, Any], text: str, working_directory: Path
) -> tuple[str | None, str | None]:
    hook = definition["hook"]
    confirmation_context = confirmed(text, hook)
    if confirmation_context:
        return None, confirmation_context
    answers: dict[str, dict[str, Any]] = {}
    # 每个 question 均以独立请求执行；不把某一题的输出传给其它题。
    for name, question in definition["questions"].items():
        single = {**definition, "questions": {name: question}}
        answers[name] = answer_for(request_decision(single, text, working_directory), name)
    reasons = review_reasons(definition, answers)
    if not reasons:
        return None, None
    on_review = hook.get("on_review", {})
    if not isinstance(on_review, dict) or on_review.get("action") != "block":
        raise ValueError("命中 hook.review_when 时仅支持 on_review.action: block")
    reason = on_review.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ValueError("hook.on_review.reason 必须是非空字符串")
    return reason.format(reasons="；".join(reasons)), None


def evaluate(event: dict[str, Any]) -> dict[str, Any] | None:
    settings, _ = load_settings()
    if not settings["jev_prompt_hook"]:
        return None
    text = input_text(event)
    cwd_value = event.get("cwd")
    cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value.strip() else Path.cwd()
    contexts: list[str] = []
    for definition in project_hook_decisions(cwd):
        reason, context = evaluate_definition(definition, text, cwd)
        if reason:
            return block(reason)
        if context:
            contexts.append(context)
    if not contexts:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(contexts)}}


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        result = evaluate(event)
    except Exception as exc:
        result = block(f"JEV Prompt Hook 运行失败，本轮请求已停止：{exc}")
        record_operation("jev_prompt_hook", result="error", details={"error": str(exc)})
    else:
        record_operation("jev_prompt_hook", details={"decision": result.get("decision", "allow") if result else "allow"})
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
