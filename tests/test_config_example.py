"""验证 plugin-utils 配置示例的位置、结构和运行时字段覆盖。"""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills" / "plugin-utils" / "example" / "config.yml"


class ConfigExampleTests(unittest.TestCase):
    """保证规范示例可复制使用，且仓库中不存在第二份完整模板。"""

    def test_example_is_parseable_and_covers_supported_features(self) -> None:
        """示例必须可解析，并覆盖代码支持的全部功能字段。"""
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
        """完整示例只能由 plugin-utils Skill 维护。"""
        self.assertTrue(EXAMPLE.is_file())
        self.assertFalse((ROOT / "wttch-config-example.yml").exists())
        instructions = (ROOT / "skills" / "plugin-utils" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("skills/plugin-utils/example/config.yml", instructions)


if __name__ == "__main__":
    unittest.main()
