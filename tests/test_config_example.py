import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills" / "plugin-utils" / "example" / "config.yml"


class ConfigExampleTests(unittest.TestCase):
    def test_example_is_parseable_and_covers_supported_features(self) -> None:
        data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)

        import sys

        sys.path.insert(0, str(ROOT / "runtime"))
        from settings import FEATURE_SCHEMA

        self.assertEqual(set(data["features"]), set(FEATURE_SCHEMA))
        self.assertEqual(
            set(data["openrouter"]), {"api_key", "decisions_url", "timeout"}
        )

    def test_example_is_owned_by_plugin_utils(self) -> None:
        self.assertTrue(EXAMPLE.is_file())
        self.assertFalse((ROOT / "wttch-config-example.yml").exists())
        instructions = (ROOT / "skills" / "plugin-utils" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("skills/plugin-utils/example/config.yml", instructions)


if __name__ == "__main__":
    unittest.main()
