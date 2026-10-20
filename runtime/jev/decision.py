#!/usr/bin/env python3
"""发现并直接执行 JEV 决策。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

# 既支持 ``python runtime/jev/main.py``，也支持从 runtime 包导入。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wttch_config import load_config, openrouter_api_key
from hooks import UserPromptSubmitInput, UserPromptSubmitOutput
from wttch_logging import record_jev_operation
from jev.history import append_prompt


PROJECT_DECISION_ROOT = Path(".agents") / "wttch" / "jev-decisions"
DEFAULT_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
USER_PROMPT_ACTIONS = {"allow", "warn", "block"}
CONTINUITY_ACTIONS = {"skip", "primary", "decision"}
DEFAULT_HISTORY_MESSAGES = 8


def user_prompt_submit_config(definition: dict) -> dict | None:
    """返回决策中显式声明的 UserPromptSubmit 适配配置。

    Hook 配置只能位于 ``hook.user_prompt_submit``。遇到旧的顶层写法时主动报错，避免
    旧配置被静默忽略；遇到未知 Hook 名称也立即拒绝，使拼写错误不会导致保护失效。
    未声明 ``hook`` 时返回 ``None``，表示该决策只能通过 CLI 手动执行。
    """
    if "user_prompt_submit" in definition:
        raise ValueError("user_prompt_submit 已迁移到 hook.user_prompt_submit")
    hook = definition.get("hook")
    if hook is None:
        return None
    if not isinstance(hook, dict):
        raise ValueError("hook 必须是对象")
    unknown_hooks = set(hook) - {"user_prompt_submit"}
    if unknown_hooks:
        raise ValueError(f"不支持的 JEV Hook：{', '.join(sorted(unknown_hooks))}")
    routing = hook.get("user_prompt_submit")
    if routing is not None and not isinstance(routing, dict):
        raise ValueError("hook.user_prompt_submit 必须是对象")
    return routing


def validate_user_prompt_submit(definition: dict) -> None:
    """校验可选的 UserPromptSubmit 分流配置。

    ``noul`` 的值是命题为真的概率，因此该命题必须以“可安全自动处理”这类
    正向形式描述。运行时可据此配置将高概率、待确认和低概率分别映射为 Hook
    的 allow、warn 或 block 响应。
    """
    routing = user_prompt_submit_config(definition)
    if routing is None:
        return

    display_name = definition.get("name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("声明 hook.user_prompt_submit 的决策必须提供非空 name")

    question_name = routing.get("question")
    questions = definition["questions"]
    if (
        not isinstance(question_name, str)
        or question_name not in questions
        or questions[question_name].get("type") != "noul"
    ):
        raise ValueError("hook.user_prompt_submit.question 必须引用一个 noul 问题")

    thresholds = routing.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("hook.user_prompt_submit.thresholds 必须是对象")
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
            "hook.user_prompt_submit 阈值必须在 0 到 1 之间，且 "
            "uncertain_at_or_above 小于 allow_at_or_above"
        )

    actions = routing.get("actions")
    if not isinstance(actions, dict) or set(actions) != {"allow", "uncertain", "deny"}:
        raise ValueError("hook.user_prompt_submit.actions 必须包含 allow、uncertain、deny")
    for branch, output in actions.items():
        if (
            not isinstance(output, dict)
            or set(output) != {"action", "message"}
            or output["action"] not in USER_PROMPT_ACTIONS
            or not isinstance(output["message"], str)
            or not output["message"].strip()
        ):
            raise ValueError(
                f"hook.user_prompt_submit.actions.{branch} 必须包含有效的 action 和非空 message"
            )
    continuity = routing.get("continuity")
    if continuity is None:
        return
    if not isinstance(continuity, dict):
        raise ValueError("hook.user_prompt_submit.continuity 必须是对象")
    if set(continuity) != {"max_messages", "decision", "question", "routes"}:
        raise ValueError("continuity 必须包含 max_messages、decision、question 和 routes")
    max_messages = continuity["max_messages"]
    if isinstance(max_messages, bool) or not isinstance(max_messages, int) or not 1 <= max_messages <= 100:
        raise ValueError("continuity.max_messages 必须是 1 到 100 的整数")
    if not isinstance(continuity["decision"], str) or not continuity["decision"].strip():
        raise ValueError("continuity.decision 必须是非空项目 JEV 名称")
    if not isinstance(continuity["question"], str) or not continuity["question"].strip():
        raise ValueError("continuity.question 必须是非空问题名称")
    routes = continuity["routes"]
    if not isinstance(routes, dict) or not routes:
        raise ValueError("continuity.routes 必须是非空对象")
    for answer, route in routes.items():
        if not isinstance(answer, str) or not isinstance(route, dict):
            raise ValueError("continuity.routes 必须以字符串答案映射到对象")
        allowed = {"action", "message", "decision"}
        if set(route) - allowed or not isinstance(route.get("action"), str):
            raise ValueError(f"continuity.routes.{answer} 格式无效")
        if route["action"] not in CONTINUITY_ACTIONS:
            raise ValueError(f"continuity.routes.{answer}.action 无效")
        if "message" in route and (not isinstance(route["message"], str) or not route["message"].strip()):
            raise ValueError(f"continuity.routes.{answer}.message 必须是非空字符串")
        if route["action"] == "decision":
            if not isinstance(route.get("decision"), str) or not route["decision"].strip():
                raise ValueError(f"continuity.routes.{answer}.decision 必须是非空项目 JEV 名称")
        elif "decision" in route:
            raise ValueError(f"continuity.routes.{answer}.decision 仅可用于 decision 动作")


def decision_files(cwd: Path | None = None) -> list[Path]:
    """返回当前项目显式安装的 JEV 决策文件，并按文件名稳定排序。

    插件自带 ``skills/jev-gate/example`` 不在搜索路径中，因此示例不会被自动列出、解析
    或执行。用户必须先把示例复制到项目目录，完成一次明确的启用动作。
    """
    project_root = (cwd or Path.cwd()) / PROJECT_DECISION_ROOT
    return sorted(project_root.glob("*.yml"), key=lambda path: path.stem)


def load_decision(path: Path) -> dict:
    """读取并校验一个项目决策或只读示例。

    基础校验保证版本、问题集合、问题类型、提示语和判定标准完整；随后校验可选的
    UserPromptSubmit 映射。函数只返回通过校验的字典，后续执行路径可以依赖这些结构，
    无需在请求 OpenRouter 前重复进行形状检查。
    """
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
    """仅在项目决策目录中按文件名或 stem 解析可执行决策。

    不接受任意路径，也不回退到插件示例目录，从入口处阻止绕过“复制后才启用”的约束。
    """
    for path in decision_files(cwd):
        if path.stem == name or path.name == name:
            return path
    raise FileNotFoundError(f"项目 JEV 决策不存在：{name}")


def request_decision(definition: dict, state: str, working_directory: Path | None = None) -> dict:
    """调用 OpenRouter Decisions API，并返回经过顶层类型检查的对象。

    API Key、端点和超时只从目标项目配置读取，禁止通过继承环境变量跨项目复用凭据。
    网络、HTTP 与超时错误统一包装为 ``RuntimeError``，让 CLI 和 Hook 各自决定如何向
    用户呈现；每次调用都会将请求、输出（或失败类型）与耗时写入本地文件日志。响应
    不是 JSON 对象时也拒绝继续，避免后续分支误判。
    """
    payload = {
        "model": definition.get("model", "typesafe/jev-1.13"),
        "state": state,
        "questions": definition["questions"],
    }
    # 所有 JEV 类型及 Hook 都经过这个入口。请求与响应分别记录，便于按一次判决完整
    # 还原输入、输出和耗时；payload 不包含从项目配置读取的 API Key。
    record_jev_operation(
        "jev_decision_input",
        details={"input": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    )
    started_at = perf_counter()
    try:
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
        with urlopen(request, timeout=float(openrouter.get("timeout", 60))) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(response_payload, dict):
            raise RuntimeError("JEV 响应必须是 JSON 对象")
    except (HTTPError, URLError, TimeoutError) as exc:
        error = RuntimeError(f"JEV 请求失败：{exc}")
        record_jev_operation(
            "jev_decision_output",
            result="error",
            details={
                "output": json.dumps({"error": type(error).__name__}, ensure_ascii=False),
                "runtime_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        raise error from exc
    except Exception as exc:
        record_jev_operation(
            "jev_decision_output",
            result="error",
            details={
                "output": json.dumps({"error": type(exc).__name__}, ensure_ascii=False),
                "runtime_ms": round((perf_counter() - started_at) * 1000, 3),
            },
        )
        raise
    record_jev_operation(
        "jev_decision_output",
        details={
            "output": json.dumps(response_payload, ensure_ascii=False, sort_keys=True),
            "runtime_ms": round((perf_counter() - started_at) * 1000, 3),
        },
    )
    return response_payload


def find_user_prompt_decision(cwd: Path) -> dict | None:
    """发现当前项目唯一启用 UserPromptSubmit 的决策。

    没有项目决策目录或没有声明该 Hook 时返回 ``None``。若同时存在多个绑定，因执行
    顺序和合并语义不明确而直接报错，要求项目维护者只保留一个自动提示路由器。
    """
    decision_dir = cwd / PROJECT_DECISION_ROOT
    if not decision_dir.is_dir():
        return None
    matches = [
        definition
        for path in decision_dir.glob("*.yml")
        if user_prompt_submit_config(definition := load_decision(path)) is not None
    ]
    if len(matches) > 1:
        raise ValueError("一个项目只能启用一个带 hook.user_prompt_submit 的 JEV 决策")
    return matches[0] if matches else None


def get_noul_probability(response: dict, question: str) -> float:
    """从 Decisions API 响应提取指定问题的 noul 概率。

    只接受 0 到 1 之间的数值，并显式排除 Python 中属于 ``int`` 子类的布尔值，避免
    ``true``/``false`` 被错误当作 1/0 的可信概率。
    """
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
    """把正向命题概率映射到 allow、uncertain 或 deny 分支。

    阈值使用“含下界”语义：等于 allow 阈值进入 allow，等于 uncertain 阈值进入
    uncertain；只有低于 uncertain 阈值才进入 deny。该边界与 YAML 字段名
    ``*_at_or_above`` 保持一致。
    """
    thresholds = routing["thresholds"]
    if probability >= thresholds["allow_at_or_above"]:
        return "allow"
    if probability >= thresholds["uncertain_at_or_above"]:
        return "uncertain"
    return "deny"


def response_for_probability(
    routing: dict, probability: float, display_name: str
) -> UserPromptSubmitOutput:
    """把概率分支配置转换为强类型 UserPromptSubmit 输出。

    ``allow`` 和 ``warn`` 都让请求继续，但仍通过额外上下文公开 JEV 分支、概率与项目
    消息。若需模型询问用户，调用方应在 YAML 的 ``message`` 中写入明确的助手指令；只有
    ``block`` 才产生协议级阻止。这样 YAML 动作控制执行效果，分支名称只表达分类结果，
    不会被误当作固定权限决定。
    """
    branch = branch_for_probability(routing, probability)
    output = routing["actions"][branch]
    message = (
        f"JEV[{display_name}] 判决结果：{branch}；noul 可能性：{probability:.1%}。"
        f"{output['message']}"
    )
    if output["action"] in {"allow", "warn"}:
        return UserPromptSubmitOutput.warn(message)
    return UserPromptSubmitOutput.block(message)


def continuity_choice(response: dict, question: str) -> str:
    """从连续性 JEV 的 choice 响应中读取路由键。"""
    answers = response.get("answers")
    answer = answers.get(question) if isinstance(answers, dict) else None
    choice = answer.get("choice") if isinstance(answer, dict) else None
    if not isinstance(choice, str) or not choice:
        raise ValueError(f"连续性 JEV 未返回问题 {question} 的有效 choice")
    return choice


def prompt_state(prompt: str, recent_inputs: list[str]) -> str:
    """构造发送给 JEV 的当前输入与同一会话最近输入。"""
    return json.dumps(
        {"prompt": prompt, "recent_inputs": recent_inputs}, ensure_ascii=False
    )


def apply_continuity_route(
    event: UserPromptSubmitInput,
    routing: dict,
    recent_inputs: list[str],
) -> UserPromptSubmitOutput | None:
    """运行可选连续性判决，并按其 choice 路由本轮 UserPrompt。

    ``skip`` 直接放行主 Gate；``primary`` 由调用方继续执行声明该 Hook 的主判决；
    ``decision`` 运行指定的项目 JEV，并把其结构化结果作为当前对话上下文注入给模型。
    所有二级决策都通过 ``resolve`` 限定在项目决策目录内。
    """
    continuity = routing.get("continuity")
    if continuity is None:
        return None
    state = prompt_state(event.prompt, recent_inputs)
    continuity_definition = load_decision(resolve(continuity["decision"], Path(event.cwd)))
    choice = continuity_choice(
        request_decision(continuity_definition, state, Path(event.cwd)),
        continuity["question"],
    )
    route = continuity["routes"].get(choice)
    if not isinstance(route, dict):
        raise ValueError(f"连续性 JEV 返回了未配置的路由：{choice}")
    action = route["action"]
    record_jev_operation(
        "prompt_jev_continuity",
        details={"decision": continuity["decision"], "choice": choice, "action": action},
    )
    if action == "primary":
        return None
    message = route.get("message", f"JEV 连续性判决：{choice}。")
    if action == "skip":
        return UserPromptSubmitOutput.warn(message)
    delegated_definition = load_decision(resolve(route["decision"], Path(event.cwd)))
    delegated_response = request_decision(delegated_definition, state, Path(event.cwd))
    return UserPromptSubmitOutput.warn(
        f"{message}JEV[{delegated_definition.get('name', route['decision'])}] 响应："
        f"{json.dumps(delegated_response, ensure_ascii=False, sort_keys=True)}"
    )


def evaluate_user_prompt(event: UserPromptSubmitInput) -> UserPromptSubmitOutput | None:
    """对一个已校验的 UserPromptSubmit 实体执行项目 JEV 路由。

    未启用项目决策时返回 ``None``，保持 Hook 静默放行。启用后会把当前输入与同会话最近
    输入写入 ``~/.wttch/jev-history`` 并作为 state 发送给 JEV；可选的连续性决策可跳过
    主 Gate 或运行另一个已定义的项目 JEV。
    """
    definition = find_user_prompt_decision(Path(event.cwd))
    if definition is None:
        return None
    routing = user_prompt_submit_config(definition)
    if routing is None:
        return None
    continuity = routing.get("continuity")
    history_limit = continuity["max_messages"] if continuity else DEFAULT_HISTORY_MESSAGES
    # 以项目路径与会话 ID 共同隔离历史，避免同一会话跨项目时混入上下文。
    history_scope = f"{Path(event.cwd).resolve()}\0{event.session_id}"
    recent_inputs = append_prompt(history_scope, event.prompt, history_limit)
    continuity_result = apply_continuity_route(event, routing, recent_inputs)
    if continuity_result is not None:
        return continuity_result
    response = request_decision(
        definition,
        prompt_state(event.prompt, recent_inputs),
        Path(event.cwd),
    )
    probability = get_noul_probability(response, routing["question"])
    branch = branch_for_probability(routing, probability)
    result = response_for_probability(routing, probability, definition["name"].strip())
    record_jev_operation(
        "prompt_jev_decision",
        details={
            "question": routing["question"],
            "probability": probability,
            "branch": branch,
            "decision": result.decision if result else "allow",
        },
    )
    return result


def run_user_prompt_submit_hook() -> int:
    """从 stdin 执行 UserPromptSubmit 决策，并向 stdout 写协议实体。

    输入解析、项目配置、网络或响应格式中的任何异常都让本轮请求继续，但会注入异常
    上下文，要求模型在最终回复中警告用户；错误状态不含敏感值。若项目没有启用决策
    则不输出任何内容，表示放行。
    """
    try:
        result = evaluate_user_prompt(UserPromptSubmitInput.load_json(sys.stdin))
    except Exception as exc:
        result = UserPromptSubmitOutput.error_warning(
            f"UserPrompt JEV Gate 未执行：{exc}。本轮请求将继续。"
        )
        record_jev_operation("prompt_jev_decision", result="error")
    if result is not None:
        print(result.dump_json())
    return 0


def run(decision: Path, request_input: dict) -> int:
    """执行 CLI 指定决策，并把 Decisions API 原始对象写入 stdout。

    CLI 输入必须包含字符串 ``state``；与 Hook 路径不同，此入口不把响应映射成 Codex
    权限决定，方便 Skill 查看完整答案并进行人工解释或调试。
    """
    definition = load_decision(decision)
    state = request_input.get("state")
    if not isinstance(state, str):
        raise ValueError("JEV 输入必须包含字符串字段 state")
    print(json.dumps(request_decision(definition, state, Path.cwd()), ensure_ascii=False))
    return 0


def list_decisions() -> int:
    """列出当前项目可执行决策，不包含插件自带示例。"""
    print(json.dumps([
        {
            "name": path.stem,
            "file": str(path),
            "group": load_decision(path).get("group", ""),
            "source": "project",
        }
        for path in decision_files()
    ], ensure_ascii=False, indent=2))
    return 0


def run_named_decision(name: str) -> int:
    """从 stdin 读取手动决策请求，解析项目决策名称后执行。"""
    request_input = json.load(sys.stdin)
    if not isinstance(request_input, dict):
        raise ValueError("JEV 输入必须是 JSON 对象")
    return run(resolve(name), request_input)
