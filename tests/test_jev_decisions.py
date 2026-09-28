import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from jev_gate.policy import load_policy  # noqa: E402


class JEVDecisionTypeTests(unittest.TestCase):
    decision_dir = ROOT / ".agents" / "wttch" / "jev"

    def assert_decision_type(self, name: str, expected: str) -> None:
        policy = load_policy(self.decision_dir / name)
        self.assertEqual(policy["type"], expected)
        self.assertIn(policy["defaults"]["action"], {"allow", "deny", "review"})

    def test_choice_decision(self) -> None:
        self.assert_decision_type("sample-choice.yml", "choice")

    def test_noul_decision(self) -> None:
        self.assert_decision_type("sample-noul.yml", "noul")

    def test_score_decision(self) -> None:
        self.assert_decision_type("sample-score.yml", "score")


if __name__ == "__main__":
    unittest.main()
