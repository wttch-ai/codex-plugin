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


if __name__ == "__main__":
    unittest.main()
