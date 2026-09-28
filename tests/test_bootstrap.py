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
        self.digest = self.root / "requirement.md5"
        self.log = self.root / "runtime.log"

    def test_digest_normalizes_windows_newlines(self) -> None:
        self.requirements.write_bytes(b"PyYAML>=6.0\r\n")
        expected = "0e4d2667e557b1b81b493cb7d78d8c3b"
        with patch.object(bootstrap, "REQUIREMENTS_PATH", self.requirements):
            self.assertEqual(bootstrap.requirements_digest(), expected)

    def test_mismatch_uses_actual_digest_and_records_auto_sync(self) -> None:
        self.requirements.write_text("PyYAML>=6.0\n", encoding="utf-8")
        self.digest.write_text("0" * 32, encoding="utf-8")
        with (
            patch.object(bootstrap, "REQUIREMENTS_PATH", self.requirements),
            patch.object(bootstrap, "REQUIREMENTS_DIGEST_PATH", self.digest),
            patch.dict(os.environ, {"WTTCH_PLUGIN_RUNTIME_LOG": str(self.log)}),
        ):
            result = bootstrap.declared_digest()
            self.assertEqual(result, bootstrap.requirements_digest())

        content = self.log.read_text(encoding="utf-8")
        self.assertIn("依赖指纹比对", content)
        self.assertIn("预期值=", content)
        self.assertIn("实际值=", content)
        self.assertIn("是否一致=False", content)
        self.assertIn("自动同步依赖", content)

    def test_settings_values_are_loaded_from_project_config(self) -> None:
        config = self.root / ".agents" / "wttch" / "config.yml"
        config.parent.mkdir(parents=True)
        config.write_text("features:\n  model_gate: false\n", encoding="utf-8")
        loaded, catalog = settings.load_settings(self.root)

        self.assertFalse(loaded["model_gate"])
        self.assertIn("model_gate", catalog)

    def test_setting_value_parser_handles_common_inputs(self) -> None:
        catalog = settings.load_feature_catalog()
        self.assertFalse(settings.parse_setting_value(catalog["model_gate"], "off"))
        self.assertEqual(
            settings.parse_setting_value(catalog["blocked_models"], "gpt-6-luna,gpt-6-sol"),
            ["gpt-6-luna", "gpt-6-sol"],
        )


if __name__ == "__main__":
    unittest.main()
