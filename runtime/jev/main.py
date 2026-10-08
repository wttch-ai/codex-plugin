#!/usr/bin/env python3
"""发现并直接执行 JEV 决策。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

# 既支持 ``python runtime/jev/main.py``，也支持从 runtime 包导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wttch_config import load_config, openrouter_api_key
from hooks import UserPromptSubmitInput, UserPromptSubmitOutput
from operation_log import record as record_operation


BUILTIN_DECISION_ROOT = Path(__file__).resolve().parents[2] / "skills" / "jev-gate" / "decisions"
PROJECT_DECISION_ROOT = Path(".agents") / "wttch" / "jev-decisions"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
USER_PROMPT_ACTIONS = {"allow", "warn", "block"}


def validate_user_prompt_submit(definition: dict) -> None:
    """校验可选的 UserPromptSubmit 分流配置。

    ``noul`` 的值是命题为真的概率，因此该命题必须以“可安全自动处理”这类
    正向形式描述。运行时可据此配置将高概率、待确认和低概率分别映射为 Hook
    的 allow、warn 或 block 响应。
    """
    routing = definition.get("user_prompt_submit")
    if routing is None:
        return
    if not isinstance(routing, dict):
        raise ValueError("user_prompt_submit 必须是对象")

    question_name = routing.get("question")
    questions = definition["questions"]
    if (
        not isinstance(question_name, str)
        or question_name not in questions
        or questions[question_name].get("type") != "noul"
    ):
        raise ValueError("user_prompt_submit.question 必须引用一个 noul 问题")

    thresholds = routing.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("user_prompt_submit.thresholds 必须是对象")
    allow_at = thresholds.get("allow_at_or_above")
    uncertain_at = thresholds.get("uncertain_at_or_above")
    if (
        not isinstance(allow_at, (int, float))
        or isinstance(allow_at, bool)
        or not isinstance(uncertain_at, (int, float))
        or isinstance(uncertain_at, bool)
        or not 0 <= allow_at <= 1
        or not 0 <= uncertain_at <= 1
        or uncertain_at >= allow_at
    ):
        raise ValueError(
            "user_prompt_submit 阈值必须在 0 到 1 之间，且 "
            "uncertain_at_or_above 小于 allow_at_or_above"
        )

    actions = routing.get("actions")
    if not isinstance(actions, dict) or set(actions) != {"allow", "uncertain", "deny"}:
        raise ValueError("user_prompt_submit.actions 必须包含 allow、uncertain、deny")
    for branch, output in actions.items():
        if (
            not isinstance(output, dict)
            or set(output) != {"action", "message"}
            or output["action"] not in USER_PROMPT_ACTIONS
            or not isinstance(output["message"], str)
            or not output["message"].strip()
        ):
            raise ValueError(
                f"user_prompt_submit.actions.{branch} 必须包含有效的 action 和非空 message"
            )


def decision_files(cwd: Path | None = None) -> list[Path]:
    """返回内置和当前项目的 JEV 决策，项目同名文件优先。"""
    project_root = (cwd or Path.cwd()) / PROJECT_DECISION_ROOT
    paths: dict[str, Path] = {path.stem: path for path in BUILTIN_DECISION_ROOT.glob("*.yml")}
    paths.update({path.stem: path for path in project_root.glob("*.yml")})
    return sorted(paths.values(), key=lambda path: path.stem)


def load_decision(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"JEV 决策格式无效：{path}")
    questions = data.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise ValueError(f"JEV 决策缺少 questions：{path}")
    for name, question in questions.items():
        if not isinstance(question, dict):
            raise ValueError(f"JEV 问题格式无效：{name}")
        if question.get("type") not in {"choice", "noul", "score"}:
            raise ValueError(f"JEV 问题类型无效：{name}")
        if not isinstance(question.get("instructions"), str):
            raise ValueError(f"JEV 问题缺少 instructions：{name}")
        if not question.get("criteria"):
            raise ValueError(f"JEV 问题缺少 criteria：{name}")
    validate_user_prompt_submit(data)
    return data


def resolve(name: str, cwd: Path | None = None) -> Path:
    candidate = Path(name)
    if candidate.is_file():
        return candidate.resolve()
    for path in decision_files(cwd):
        if path.stem == name or path.name == name:
            return path
    raise FileNotFoundError(f"JEV 决策不存在：{name}")


def request_decision(definition: dict, state: str, working_directory: Path | None = None) -> dict:
    """执行一次 JEV 请求并返回已解码的对象，供 CLI 与 Hook 共用。"""
    payload = {
        "model": definition.get("model", "typesafe/jev-1.13"),
        "state": state,
        "questions": definition["questions"],
    }
    # 凭据只允许来自当前项目配置，避免环境继承导致跨项目误用 Key。
    key = openrouter_api_key(working_directory)
    if not key:
        raise RuntimeError(
            "OpenRouter API key is not configured: set "
            "<project>/.agents/wttch/config.yml openrouter.api_key"
        )
    config = load_config(working_directory)
    openrouter = config.get("openrouter", {})
    if not isinstance(openrouter, dict):
        raise ValueError(".agents/wttch/config.yml openrouter must be an object")
    request = Request(
        str(openrouter.get("decisions_url", DEFAULT_ENDPOINT)),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=float(openrouter.get("timeout", 60))) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"JEV 请求失败：{exc}") from exc
    if not isinstance(response_payload, dict):
        raise RuntimeError("JEV 响应必须是 JSON 对象")
    return response_payload


def find_user_prompt_decision(cwd: Path) -> dict | None:
    """返回当前项目唯一启用 UserPromptSubmit 的决策。"""
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


def get_noul_probability(response: dict, question: str) -> float:
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


def branch_for_probability(routing: dict, probability: float) -> str:
    """将正向 noul 概率划入 allow、uncertain 或 deny 分支。"""
    thresholds = routing["thresholds"]
    if probability >= thresholds["allow_at_or_above"]:
        return "allow"
    if probability >= thresholds["uncertain_at_or_above"]:
        return "uncertain"
    return "deny"


def response_for_probability(
    routing: dict, probability: float
) -> UserPromptSubmitOutput:
    """将项目配置的 UserPromptSubmit 分支转为 Hook 响应。"""
    branch = branch_for_probability(routing, probability)
    output = routing["actions"][branch]
    message = (
        f"JEV 决策结果：{branch}；noul 可能性：{probability:.1%}。"
        f"{output['message']}"
    )
    if output["action"] in {"allow", "warn"}:
        return UserPromptSubmitOutput.warn(message)
    return UserPromptSubmitOutput.block(message)


def evaluate_user_prompt(event: UserPromptSubmitInput) -> UserPromptSubmitOutput | None:
    """执行当前项目显式启用的 UserPromptSubmit JEV 决策。"""
    definition = find_user_prompt_decision(Path(event.cwd))
    if definition is None:
        return None
    routing = definition["user_prompt_submit"]
    response = request_decision(
        definition,
        json.dumps({"prompt": event.prompt}, ensure_ascii=True),
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


def run_user_prompt_submit_hook() -> int:
    """执行 UserPromptSubmit Hook，并把配置或服务错误视为阻止。"""
    try:
        raw = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ValueError("hook input must be a JSON object")
        result = evaluate_user_prompt(UserPromptSubmitInput(**raw))
    except Exception as exc:
        result = UserPromptSubmitOutput.block(f"UserPrompt JEV Gate 未执行：{exc}")
        record_operation("prompt_jev_gate", result="error")
    if result is not None:
        print(result.dump_json())
    return 0


def run(decision: Path, request_input: dict) -> int:
    definition = load_decision(decision)
    state = request_input.get("state")
    if not isinstance(state, str):
        raise ValueError("JEV 输入必须包含字符串字段 state")
    print(json.dumps(request_decision(definition, state, Path.cwd()), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("user-prompt-submit")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("name")
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps([
            {
                "name": path.stem,
                "file": str(path),
                "group": load_decision(path).get("group", ""),
                "source": "builtin" if BUILTIN_DECISION_ROOT in path.parents else "project",
            }
            for path in decision_files()
        ], ensure_ascii=False, indent=2))
        return 0
    if args.command == "user-prompt-submit":
        return run_user_prompt_submit_hook()
    request_input = json.load(sys.stdin)
    if not isinstance(request_input, dict):
        raise ValueError("JEV 输入必须是 JSON 对象")
    return run(resolve(args.name), request_input)


if __name__ == "__main__":
    raise SystemExit(main())
