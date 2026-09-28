import sys
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev_gate.policy import load_policy  # noqa: E402
import jev_prompt_hook  # noqa: E402
from jev.main import load_decision  # noqa: E402


class JEVDecisionTypeTests(unittest.TestCase):
    decision_dir = ROOT / "skills" / "jev-gate" / "decisions"

    def assert_decision_type(self, name: str, expected: str) -> None:
        policy = load_policy(self.decision_dir / name)
        types = {question["type"] for question in policy["questions"].values()}
        self.assertEqual(types, {expected})

    def test_choice_decision(self) -> None:
        self.assert_decision_type("sample-choice.yml", "choice")
        self.assertEqual(load_policy(self.decision_dir / "sample-choice.yml")["group"], "内置示例")
        criteria = next(iter(load_policy(self.decision_dir / "sample-choice.yml")["questions"].values()))["criteria"]
        self.assertEqual(set(criteria), {"billing", "technical", "sales"})

    def test_noul_decision(self) -> None:
        self.assert_decision_type("sample-noul.yml", "noul")
        outcomes = next(iter(load_policy(self.decision_dir / "sample-noul.yml")["questions"].values()))["criteria"]
        self.assertEqual(set(outcomes), {"true", "false"})
        self.assertTrue(all(outcomes.values()))

    def test_score_decision(self) -> None:
        self.assert_decision_type("sample-score.yml", "score")
        self.assertEqual(load_policy(self.decision_dir / "sample-score.yml")["group"], "内置示例")
        levels = next(iter(load_policy(self.decision_dir / "sample-score.yml")["questions"].values()))["criteria"]
        self.assertEqual(len(levels), 4)
        self.assertTrue(all(isinstance(item, str) and item for item in levels))

    def test_prompt_hook_blocks_for_yaml_threshold_review(self) -> None:
        definition = {"questions": {"scope": {"type": "choice"}}, "hook": {
            "event": "UserPromptSubmit", "review_when": {"scope": {"probability_below": 0.80}},
            "on_review": {"action": "block", "reason": "请确认：{reasons}"},
        }}
        with patch.object(jev_prompt_hook, "request_decision", return_value={"answers": {"scope": {"probability": 0.79}}}) as request:
            reason, context = jev_prompt_hook.evaluate_definition(definition, "修复 ParserTest")
        self.assertEqual(reason, "请确认：scope.probability 低于 0.8")
        self.assertIsNone(context)
        self.assertEqual(request.call_count, 1)

    def test_prompt_hook_confirmation_uses_yaml_pattern(self) -> None:
        definition = {"questions": {}, "hook": {"event": "UserPromptSubmit", "confirmation": {
            "pattern": r"^route:(work_task)$", "context": "selected {0}",
        }}}
        with patch.object(jev_prompt_hook, "request_decision") as request:
            reason, context = jev_prompt_hook.evaluate_definition(definition, "route:work_task")
        self.assertIsNone(reason)
        self.assertEqual(context, "selected work_task")
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
