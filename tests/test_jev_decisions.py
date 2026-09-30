import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev_gate.policy import load_policy  # noqa: E402
from jev.main import load_decision  # noqa: E402
from prompt_jev_gate import branch_for_probability, get_noul_probability, response_for_probability  # noqa: E402


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
        decision = load_decision(self.decision_dir / "sample-noul.yml")
        self.assertEqual({question["type"] for question in decision["questions"].values()}, {"noul"})
        outcomes = next(iter(decision["questions"].values()))["criteria"]
        self.assertEqual(set(outcomes), {"true", "false"})
        self.assertTrue(all(outcomes.values()))
        routing = decision["user_prompt_submit"]
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
        routing = load_decision(self.decision_dir / "sample-noul.yml")["user_prompt_submit"]
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

    def test_score_decision(self) -> None:
        self.assert_decision_type("sample-score.yml", "score")
        self.assertEqual(load_policy(self.decision_dir / "sample-score.yml")["group"], "内置示例")
        levels = next(iter(load_policy(self.decision_dir / "sample-score.yml")["questions"].values()))["criteria"]
        self.assertEqual(len(levels), 4)
        self.assertTrue(all(isinstance(item, str) and item for item in levels))

if __name__ == "__main__":
    unittest.main()
