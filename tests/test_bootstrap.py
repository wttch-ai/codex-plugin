import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


RUNTIME_ROOT = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

import bootstrap  # noqa: E402
import settings  # noqa: E402


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.requirements = self.root / "requirements.txt"
        self.log = self.root / "runtime.log"

    def test_digest_normalizes_windows_newlines(self) -> None:
        self.requirements.write_bytes(b"PyYAML>=6.0\r\n")
        expected = "0e4d2667e557b1b81b493cb7d78d8c3b"
        with patch.object(bootstrap, "REQUIREMENTS_PATH", self.requirements):
            self.assertEqual(bootstrap.requirements_digest(), expected)

    def test_dependency_digest_comes_from_requirements_file(self) -> None:
        self.requirements.write_text("PyYAML>=6.0\n", encoding="utf-8")
        with patch.object(bootstrap, "REQUIREMENTS_PATH", self.requirements):
            result = bootstrap.requirements_digest()
            self.assertEqual(result, bootstrap.requirements_digest())

    def test_settings_values_are_loaded_from_project_config(self) -> None:
        config = self.root / ".agents" / "wttch" / "config.yml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "features:\n"
            "  jev_gate: true\n"
            "  openrouter_review: true\n"
            "  show_decision_reason: true\n"
            "  audit_log: false\n"
            "  model_gate: false\n"
            "  model_gate_action: block\n"
            "  blocked_models: [gpt-6-luna]\n",
            encoding="utf-8",
        )
        loaded, catalog = settings.load_settings(self.root)

        self.assertFalse(loaded["model_gate"])
        self.assertIn("model_gate", catalog)

    def test_settings_require_all_project_feature_values(self) -> None:
        config = self.root / ".agents" / "wttch" / "config.yml"
        config.parent.mkdir(parents=True)
        config.write_text("features:\n  model_gate: false\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing feature"):
            settings.load_settings(self.root)


if __name__ == "__main__":
    unittest.main()
