#!/usr/bin/env python3
"""将项目级 JEV ``noul`` 决策映射到 UserPromptSubmit Hook 响应。"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from hooks import UserPromptSubmitInput, UserPromptSubmitOutput
from jev.main import load_decision, request_decision
from operation_log import record as record_operation


PROJECT_DECISION_ROOT = Path(".agents") / "wttch" / "jev-decisions"


def find_project_decision(cwd: Path) -> dict[str, Any] | None:
    """返回唯一启用 UserPromptSubmit 的项目决策，不读取插件内置示例。"""
    decision_dir = cwd / PROJECT_DECISION_ROOT
    if not decision_dir.is_dir():
        return None
    matches = [
        definition
        for path in decision_dir.glob("*.yml")
        if "user_prompt_submit" in (definition := load_decision(path))
    ]
    if len(matches) > 1:
        raise ValueError("一个项目只能启用一个带 user_prompt_submit 的 JEV 决策")
    return matches[0] if matches else None


def get_noul_probability(response: dict[str, Any], question: str) -> float:
    """从 Decisions API 响应提取经过校验的 noul 概率。"""
    answers = response.get("answers")
    answer = answers.get(question) if isinstance(answers, dict) else None
    probability = answer.get("noul") if isinstance(answer, dict) else None
    if (
        not isinstance(probability, (int, float))
        or isinstance(probability, bool)
        or not 0 <= probability <= 1
    ):
        raise ValueError(f"JEV 未返回问题 {question} 的有效 noul 概率")
    return float(probability)


def branch_for_probability(routing: dict[str, Any], probability: float) -> str:
    """将正向 noul 概率划入 allow、uncertain 或 deny 分支。"""
    thresholds = routing["thresholds"]
    if probability >= thresholds["allow_at_or_above"]:
        return "allow"
    if probability >= thresholds["uncertain_at_or_above"]:
        return "uncertain"
    return "deny"


def response_for_probability(
    routing: dict[str, Any], probability: float
) -> UserPromptSubmitOutput | None:
    """按 YAML 中配置的分支动作构造 Hook 响应。"""
    output = routing["actions"][branch_for_probability(routing, probability)]
    if output["action"] == "allow":
        return None
    if output["action"] == "warn":
        return UserPromptSubmitOutput.warn(output["message"])
    return UserPromptSubmitOutput.block(output["message"])


def evaluate(event: UserPromptSubmitInput) -> UserPromptSubmitOutput | None:
    """仅在当前项目显式配置决策时调用 JEV。"""
    definition = find_project_decision(Path(event.cwd))
    if definition is None:
        return None
    routing = definition["user_prompt_submit"]
    response = request_decision(
        definition,
        json.dumps({"prompt": event.prompt}, ensure_ascii=False),
        Path(event.cwd),
    )
    probability = get_noul_probability(response, routing["question"])
    branch = branch_for_probability(routing, probability)
    result = response_for_probability(routing, probability)
    record_operation(
        "prompt_jev_gate",
        details={
            "question": routing["question"],
            "probability": probability,
            "branch": branch,
            "decision": result.decision if result else "allow",
        },
    )
    return result


def main() -> int:
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ValueError("hook input must be a JSON object")
        result = evaluate(UserPromptSubmitInput(**raw))
    except Exception as exc:
        # 项目显式启用 Gate 后，解析或服务异常不能静默绕过项目级保护。
        result = UserPromptSubmitOutput.block(f"UserPrompt JEV Gate 未执行：{exc}")
        record_operation("prompt_jev_gate", result="error")
    if result is not None:
        print(json.dumps({key: value for key, value in asdict(result).items() if value is not None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
