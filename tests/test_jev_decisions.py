from contextlib import redirect_stdout
from io import StringIO
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev.decision import (  # noqa: E402
    branch_for_probability,
    evaluate_user_prompt,
    find_user_prompt_decision,
    get_noul_probability,
    load_decision,
    response_for_probability,
    user_prompt_submit_config,
    validate_user_prompt_submit,
)
from jev.main import build_parser, main  # noqa: E402
from jev.policy import load_policy  # noqa: E402
from hooks import UserPromptSubmitInput  # noqa: E402


class JEVDecisionTypeTests(unittest.TestCase):
    decision_dir = ROOT / "skills" / "jev-gate" / "decisions"

    def assert_decision_type(self, name: str, expected: str) -> None:
        definition = load_decision(self.decision_dir / name)
        types = {question["type"] for question in definition["questions"].values()}
        self.assertEqual(types, {expected})

    def test_choice_decision(self) -> None:
        self.assert_decision_type("sample-choice.yml", "choice")
        self.assertEqual(load_decision(self.decision_dir / "sample-choice.yml")["group"], "内置示例")
        criteria = next(iter(load_decision(self.decision_dir / "sample-choice.yml")["questions"].values()))["criteria"]
        self.assertEqual(set(criteria), {"billing", "technical", "sales"})

    def test_noul_decision(self) -> None:
        decision = load_decision(self.decision_dir / "sample-noul.yml")
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

    def test_user_prompt_submit_routes_noul_probability(self) -> None:
        routing = load_decision(self.decision_dir / "sample-noul.yml")["hook"]["user_prompt_submit"]
        self.assertEqual(branch_for_probability(routing, 0.80), "allow")
        self.assertEqual(branch_for_probability(routing, 0.40), "uncertain")
        self.assertEqual(branch_for_probability(routing, 0.39), "deny")
        self.assertIn("JEV 决策结果：allow；noul 可能性：80.0%", response_for_probability(routing, 0.80).systemMessage)
        self.assertEqual(response_for_probability(routing, 0.40).decision, "block")
        self.assertIn("JEV 决策结果：deny；noul 可能性：39.0%", response_for_probability(routing, 0.39).reason)

    def test_user_prompt_submit_rejects_invalid_noul_response(self) -> None:
        response = {"answers": {"safe_to_run": {"noul": 0.5}}}
        self.assertEqual(get_noul_probability(response, "safe_to_run"), 0.5)
        with self.assertRaises(ValueError):
            get_noul_probability({"answers": {"safe_to_run": {"noul": 1.1}}}, "safe_to_run")

    def test_legacy_top_level_hook_configuration_is_rejected(self) -> None:
        definition = load_decision(self.decision_dir / "sample-noul.yml")
        definition["user_prompt_submit"] = definition.pop("hook")["user_prompt_submit"]
        with self.assertRaisesRegex(ValueError, "已迁移到 hook.user_prompt_submit"):
            validate_user_prompt_submit(definition)

    def test_project_hook_is_discovered_automatically(self) -> None:
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
                patch("jev.decision.record_operation"),
            ):
                result = evaluate_user_prompt(event)
            request.assert_called_once()
            self.assertIsNone(result.decision)
            self.assertIn("allow", result.systemMessage)

    def test_builtin_hook_example_is_not_automatically_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(find_user_prompt_decision(Path(directory)))

    def test_plugin_mounts_user_prompt_router(self) -> None:
        manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for group in manifest["hooks"]["UserPromptSubmit"]
            for hook in group["hooks"]
        ]
        self.assertTrue(any("hook user-prompt-submit" in command for command in commands))

    def test_score_decision(self) -> None:
        self.assert_decision_type("sample-score.yml", "score")
        self.assertEqual(load_decision(self.decision_dir / "sample-score.yml")["group"], "内置示例")
        levels = next(iter(load_decision(self.decision_dir / "sample-score.yml")["questions"].values()))["criteria"]
        self.assertEqual(len(levels), 4)
        self.assertTrue(all(isinstance(item, str) and item for item in levels))

    def test_gate_policy_and_decision_schemas_are_separate(self) -> None:
        policy = load_policy(ROOT / "skills" / "jev-gate" / "hook.yml")
        self.assertGreater(len(policy["rules"]), 0)
        with self.assertRaisesRegex(ValueError, "defaults 和 rules"):
            load_policy(self.decision_dir / "sample-choice.yml")

    def test_unified_cli_command_tree(self) -> None:
        parser = build_parser()
        decision = parser.parse_args(["decision", "run", "sample-choice"])
        self.assertEqual((decision.command, decision.decision_command), ("decision", "run"))
        prompt_hook = parser.parse_args(["hook", "user-prompt-submit"])
        self.assertEqual(prompt_hook.hook_command, "user-prompt-submit")
        tool_hook = parser.parse_args([
            "hook", "pre-tool-use", "--policy", "skills/jev-gate/hook.yml"
        ])
        self.assertEqual(tool_hook.hook_command, "pre-tool-use")
        policy = parser.parse_args([
            "policy", "validate", "--policy", "skills/jev-gate/hook.yml"
        ])
        self.assertEqual(policy.policy_command, "validate")

    def test_unified_policy_validate_command(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = main([
                "policy",
                "validate",
                "--policy",
                str(ROOT / "skills" / "jev-gate" / "hook.yml"),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "rules": 3})

    def test_unified_pre_tool_use_hook_command(self) -> None:
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
            "cwd": str(ROOT),
        }
        output = StringIO()
        with (
            patch.object(sys, "stdin", StringIO(json.dumps(event))),
            patch("jev.gate.record_operation"),
            redirect_stdout(output),
        ):
            result = main([
                "hook",
                "pre-tool-use",
                "--policy",
                str(ROOT / "skills" / "jev-gate" / "hook.yml"),
            ])
        self.assertEqual(result, 0)
        hook_output = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertEqual(hook_output["hookEventName"], "PreToolUse")
        self.assertEqual(hook_output["permissionDecision"], "deny")

if __name__ == "__main__":
    unittest.main()
