import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev_gate.policy import load_policy  # noqa: E402


class JEVDecisionTypeTests(unittest.TestCase):
    decision_dir = ROOT / "skills" / "jev-gate" / "decisions"

    def assert_decision_type(self, name: str, expected: str) -> None:
        policy = load_policy(self.decision_dir / name)
        self.assertEqual(policy["type"], expected)
        self.assertTrue(policy["question"])
        self.assertTrue(policy["system_prompt"])
        self.assertIn(policy["defaults"]["action"], {"allow", "deny", "review"})

    def test_choice_decision(self) -> None:
        self.assert_decision_type("sample-choice.yml", "choice")
        self.assertEqual(load_policy(self.decision_dir / "sample-choice.yml")["group"], "内置示例")
        options = load_policy(self.decision_dir / "sample-choice.yml")["options"]
        self.assertEqual(len(options), 3)
        self.assertTrue(all(item["prompt"] for item in options))

    def test_noul_decision(self) -> None:
        self.assert_decision_type("sample-noul.yml", "noul")
        outcomes = load_policy(self.decision_dir / "sample-noul.yml")["outcomes"]
        self.assertEqual(set(outcomes), {"true", "false"})
        self.assertTrue(all(outcomes.values()))

    def test_score_decision(self) -> None:
        self.assert_decision_type("sample-score.yml", "score")
        self.assertEqual(load_policy(self.decision_dir / "sample-score.yml")["group"], "内置示例")
        levels = load_policy(self.decision_dir / "sample-score.yml")["levels"]
        self.assertEqual(len(levels), 4)
        self.assertTrue(all(item["prompt"] for item in levels))


if __name__ == "__main__":
    unittest.main()
