import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import forbidden_server  # noqa: E402


class ForbiddenServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        config = self.root / ".agents" / "wttch" / "forbidden-server.yml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "- target: 192.168.2.29\n  action: block\n  description: blocked host\n"
            "- target: prod.example\n  action: warn\n  description: production host\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_blocks_configured_target(self) -> None:
        result = forbidden_server.evaluate({"cwd": str(self.root), "tool_input": {"command": "ssh 192.168.2.29"}})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_warns_without_blocking(self) -> None:
        result = forbidden_server.evaluate({"cwd": str(self.root), "tool_input": {"url": "https://prod.example/api"}})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_block_precedes_warn(self) -> None:
        result = forbidden_server.evaluate({"cwd": str(self.root), "tool_input": {"command": "curl prod.example; ssh 192.168.2.29"}})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
