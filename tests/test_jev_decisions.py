"""验证项目 JEV 决策发现、校验、执行和 UserPromptSubmit 路由。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev.decision import (  # noqa: E402
    branch_for_probability,
    decision_files,
    evaluate_user_prompt,
    find_user_prompt_decision,
    get_noul_probability,
    load_decision,
    request_decision,
    response_for_probability,
    resolve,
    user_prompt_submit_config,
    validate_user_prompt_submit,
)
from jev.main import build_parser  # noqa: E402
from hooks import UserPromptSubmitInput  # noqa: E402


class JEVDecisionTypeTests(unittest.TestCase):
    """保证示例只供复制，并验证项目安装后的自动 Hook 行为。

    测试把插件示例与临时项目目录严格分开：示例用于校验格式，只有复制到临时项目
    ``.agents/wttch/jev-decisions`` 后才应被发现。这能防止未来重构意外把示例当作默认
    启用策略，进而在所有安装插件的项目中执行网络决策。
    """

    decision_dir = ROOT / "skills" / "jev-gate" / "example"

    def assert_decision_type(self, name: str, expected: str) -> None:
        """断言一个示例中的所有问题都使用预期 JEV 类型。"""
        definition = load_decision(self.decision_dir / name)
        types = {question["type"] for question in definition["questions"].values()}
        self.assertEqual(types, {expected})

    def test_choice_decision(self) -> None:
        """choice 示例必须保留稳定的团队候选项和示例分组。"""
        self.assert_decision_type("sample-choice.yml", "choice")
        self.assertEqual(load_decision(self.decision_dir / "sample-choice.yml")["group"], "内置示例")
        criteria = next(iter(load_decision(self.decision_dir / "sample-choice.yml")["questions"].values()))["criteria"]
        self.assertEqual(set(criteria), {"billing", "technical", "sales"})

    def test_noul_decision(self) -> None:
        """noul 示例必须使用正反标准、嵌套 Hook 配置和完整三分支动作。"""
        decision = load_decision(self.decision_dir / "sample-noul.yml")
        self.assertEqual(decision["name"], "自动处理判定")
        self.assertEqual({question["type"] for question in decision["questions"].values()}, {"noul"})
        outcomes = next(iter(decision["questions"].values()))["criteria"]
        self.assertEqual(set(outcomes), {"true", "false"})
        self.assertTrue(all(outcomes.values()))
        routing = decision["hook"]["user_prompt_submit"]
        self.assertEqual(routing["question"], "safe_to_run")
        self.assertEqual(routing["thresholds"], {
            "allow_at_or_above": 0.80,
            "uncertain_at_or_above": 0.40,
        })
        self.assertEqual(routing["actions"]["uncertain"], {
            "action": "block",
            "message": "JEV 判断可信度不足，请明确确认后重新提交。",
        })

    def test_orchestrator_routing_example_uses_distinct_warnings(self) -> None:
        """编排器示例应为三种可信区间提供不同提示，但都保持请求继续。

        高概率提示当前维护编排器，低概率提示交给业务 Agent，中间分支要求先澄清边界；
        三者均使用 warn，避免示例未经项目调整就强制阻止用户。
        """
        decision = load_decision(self.decision_dir / "orchestrator-routing.yml")
        routing = decision["hook"]["user_prompt_submit"]
        self.assertEqual(routing["question"], "orchestrator_maintenance")
        self.assertEqual(
            {branch["action"] for branch in routing["actions"].values()}, {"warn"}
        )
        messages = {
            branch: output["message"]
            for branch, output in routing["actions"].items()
        }
        self.assertEqual(len(set(messages.values())), 3)
        self.assertIn("当前编排器项目", messages["allow"])
        self.assertIn("business-code-agent", messages["deny"])
        orchestrator_output = response_for_probability(routing, 0.90, decision["name"])
        business_output = response_for_probability(routing, 0.10, decision["name"])
        self.assertIsNone(orchestrator_output.decision)
        self.assertIn("当前编排器项目", orchestrator_output.systemMessage)
        self.assertIsNone(business_output.decision)
        self.assertIn("business-code-agent", business_output.systemMessage)

    def test_user_prompt_submit_routes_noul_probability(self) -> None:
        """验证阈值等号边界和 YAML action 到 Hook 响应的映射。"""
        routing = load_decision(self.decision_dir / "sample-noul.yml")["hook"]["user_prompt_submit"]
        self.assertEqual(branch_for_probability(routing, 0.80), "allow")
        self.assertEqual(branch_for_probability(routing, 0.40), "uncertain")
        self.assertEqual(branch_for_probability(routing, 0.39), "deny")
        self.assertIn("JEV[自动处理判定] 判决结果：allow；noul 可能性：80.0%", response_for_probability(routing, 0.80, "自动处理判定").systemMessage)
        self.assertEqual(response_for_probability(routing, 0.40, "自动处理判定").decision, "block")
        self.assertIn("JEV[自动处理判定] 判决结果：deny；noul 可能性：39.0%", response_for_probability(routing, 0.39, "自动处理判定").reason)

    def test_user_prompt_submit_rejects_invalid_noul_response(self) -> None:
        """API 返回的概率必须位于闭区间 0..1，超界值不能参与路由。"""
        response = {"answers": {"safe_to_run": {"noul": 0.5}}}
        self.assertEqual(get_noul_probability(response, "safe_to_run"), 0.5)
        with self.assertRaises(ValueError):
            get_noul_probability({"answers": {"safe_to_run": {"noul": 1.1}}}, "safe_to_run")

    def test_request_decision_logs_input_output_and_runtime(self) -> None:
        """所有 JEV 类型共用的请求入口必须记录可审计的输入、输出和耗时。"""
        definition = load_decision(self.decision_dir / "sample-choice.yml")
        response = MagicMock()
        response.read.return_value = b'{"answers":{"team":{"choice":"technical"}}}'
        urlopen = MagicMock()
        urlopen.return_value.__enter__.return_value = response
        with (
            patch("jev.decision.openrouter_api_key", return_value="test-key"),
            patch("jev.decision.load_config", return_value={"openrouter": {}}),
            patch("jev.decision.urlopen", urlopen),
            patch("jev.decision.record_jev_operation") as record,
        ):
            result = request_decision(definition, "需要调查 API 错误")

        self.assertEqual(result["answers"]["team"]["choice"], "technical")
        self.assertEqual(record.call_args_list[0].args, ("jev_decision_input",))
        input_payload = json.loads(record.call_args_list[0].kwargs["details"]["input"])
        self.assertEqual(input_payload["state"], "需要调查 API 错误")
        self.assertEqual(record.call_args_list[1].args, ("jev_decision_output",))
        output_details = record.call_args_list[1].kwargs["details"]
        self.assertEqual(json.loads(output_details["output"]), result)
        self.assertGreaterEqual(output_details["runtime_ms"], 0)

    def test_request_decision_logs_runtime_when_response_is_invalid(self) -> None:
        """失败判决也必须留下输入、错误输出和耗时，避免审计链中断。"""
        definition = load_decision(self.decision_dir / "sample-choice.yml")
        response = MagicMock()
        response.read.return_value = b"[]"
        urlopen = MagicMock()
        urlopen.return_value.__enter__.return_value = response
        with (
            patch("jev.decision.openrouter_api_key", return_value="test-key"),
            patch("jev.decision.load_config", return_value={"openrouter": {}}),
            patch("jev.decision.urlopen", urlopen),
            patch("jev.decision.record_jev_operation") as record,
            self.assertRaisesRegex(RuntimeError, "响应必须是 JSON 对象"),
        ):
            request_decision(definition, "无效响应测试")

        output_call = record.call_args_list[1]
        self.assertEqual(output_call.args, ("jev_decision_output",))
        self.assertEqual(output_call.kwargs["result"], "error")
        self.assertEqual(json.loads(output_call.kwargs["details"]["output"]), {"error": "RuntimeError"})
        self.assertGreaterEqual(output_call.kwargs["details"]["runtime_ms"], 0)

    def test_legacy_top_level_hook_configuration_is_rejected(self) -> None:
        """旧顶层写法必须明确报迁移错误，不能被静默当作手动决策。"""
        definition = load_decision(self.decision_dir / "sample-noul.yml")
        definition["user_prompt_submit"] = definition.pop("hook")["user_prompt_submit"]
        with self.assertRaisesRegex(ValueError, "已迁移到 hook.user_prompt_submit"):
            validate_user_prompt_submit(definition)

    def test_hook_decision_requires_a_display_name(self) -> None:
        """自动 Hook 决策没有名称时必须拒绝，避免生成无法识别的提示。"""
        definition = load_decision(self.decision_dir / "sample-noul.yml")
        del definition["name"]
        with self.assertRaisesRegex(ValueError, "必须提供非空 name"):
            validate_user_prompt_submit(definition)

    def test_project_hook_is_discovered_automatically(self) -> None:
        """复制到项目决策目录并声明 Hook 后应被自动发现。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agents" / "wttch" / "jev-decisions" / "prompt.yml"
            target.parent.mkdir(parents=True)
            target.write_text(
                (self.decision_dir / "sample-noul.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            definition = find_user_prompt_decision(root)
            self.assertIsNotNone(definition)
            self.assertEqual(user_prompt_submit_config(definition)["question"], "safe_to_run")

    def test_discovered_project_hook_executes_automatically(self) -> None:
        """自动发现的项目决策应使用提示实体调用 API 并生成允许上下文。

        网络请求和操作日志在测试中替换为 mock，断言只关注发现、state 构造、概率路由与
        输出实体，避免测试访问真实 OpenRouter 或用户日志目录。
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agents" / "wttch" / "jev-decisions" / "prompt.yml"
            target.parent.mkdir(parents=True)
            target.write_text(
                (self.decision_dir / "sample-noul.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            event = UserPromptSubmitInput(
                session_id="session",
                transcript_path=None,
                cwd=str(root),
                hook_event_name="UserPromptSubmit",
                model="test-model",
                turn_id="turn",
                prompt="测试请求",
            )
            response = {"answers": {"safe_to_run": {"noul": 0.9}}}
            with (
                patch("jev.decision.request_decision", return_value=response) as request,
                patch("jev.decision.record_jev_operation"),
            ):
                result = evaluate_user_prompt(event)
            request.assert_called_once()
            self.assertIsNone(result.decision)
            self.assertIn("allow", result.systemMessage)

    def test_example_hook_is_not_automatically_enabled(self) -> None:
        """空项目不能因为插件目录内存在示例而启用 UserPromptSubmit 决策。"""
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(find_user_prompt_decision(Path(directory)))

    def test_examples_are_not_discovered_or_resolved(self) -> None:
        """列表和名称解析都只能访问项目目录，不能回退到插件示例。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(decision_files(root), [])
            with self.assertRaisesRegex(FileNotFoundError, "项目 JEV 决策不存在"):
                resolve("sample-choice", root)

    def test_only_project_decisions_are_discovered(self) -> None:
        """项目目录中的普通手动决策应被列出，且返回路径保持确定。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".agents" / "wttch" / "jev-decisions" / "active.yml"
            target.parent.mkdir(parents=True)
            target.write_text(
                (self.decision_dir / "sample-choice.yml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self.assertEqual(decision_files(root), [target])

    def test_plugin_mounts_user_prompt_router(self) -> None:
        """插件 Hook 清单必须把 JEV 统一入口挂载到 UserPromptSubmit。"""
        manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for group in manifest["hooks"]["UserPromptSubmit"]
            for hook in group["hooks"]
        ]
        self.assertTrue(any("hook user-prompt-submit" in command for command in commands))

    def test_score_decision(self) -> None:
        """score 示例必须保留四个由弱到强的购买意向等级。"""
        self.assert_decision_type("sample-score.yml", "score")
        self.assertEqual(load_decision(self.decision_dir / "sample-score.yml")["group"], "内置示例")
        levels = next(iter(load_decision(self.decision_dir / "sample-score.yml")["questions"].values()))["criteria"]
        self.assertEqual(len(levels), 4)
        self.assertTrue(all(isinstance(item, str) and item for item in levels))

    def test_unified_cli_command_tree(self) -> None:
        """统一 CLI 必须同时解析手动决策和 UserPromptSubmit Hook 子命令。"""
        parser = build_parser()
        decision = parser.parse_args(["decision", "run", "sample-choice"])
        self.assertEqual((decision.command, decision.decision_command), ("decision", "run"))
        prompt_hook = parser.parse_args(["hook", "user-prompt-submit"])
        self.assertEqual(prompt_hook.hook_command, "user-prompt-submit")

if __name__ == "__main__":
    unittest.main()
