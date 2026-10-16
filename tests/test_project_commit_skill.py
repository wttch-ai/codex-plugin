"""验证项目提交 Skill 的 SNOPSHOT 版本推进与双文件同步。"""

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "project-commit"
    / "scripts"
    / "update_snapshot_version.py"
)
SPEC = importlib.util.spec_from_file_location("update_snapshot_version", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ProjectCommitSkillTests(unittest.TestCase):
    """覆盖连续快照、稳定版迁移和清单/README 原子同步规则。"""

    def test_existing_snapshot_keeps_core_and_advances_timestamp(self):
        """连续快照保留核心版本并保证时间戳严格递增。"""
        current = "0.1.44-SNOPSHOT-2026-10-16T10-04-13"
        now = datetime(2026, 10, 16, 10, 4, 12)
        self.assertEqual(
            MODULE.next_snapshot_version(current, now),
            "0.1.44-SNOPSHOT-2026-10-16T10-04-14",
        )

    def test_stable_version_enters_next_patch_snapshot(self):
        """稳定版进入调试周期时提升 patch。"""
        self.assertEqual(
            MODULE.next_snapshot_version(
                "1.2.3+codex.20261016", datetime(2026, 10, 16, 11, 22, 33)
            ),
            "1.2.4-SNOPSHOT-2026-10-16T11-22-33",
        )

    def test_updates_manifest_and_readme_together(self):
        """版本脚本必须同步更新清单和 README。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / ".codex-plugin" / "plugin.json"
            manifest_path.parent.mkdir()
            manifest_path.write_text(
                json.dumps({"name": "example", "version": "2.0.0"}, indent=2) + "\n",
                encoding="utf-8",
            )
            readme_path = root / "README.md"
            readme_path.write_text(
                "# Example\n\n- 当前版本：`2.0.0`\n", encoding="utf-8"
            )

            old, new = MODULE.update_versions(
                root, datetime(2026, 10, 16, 12, 34, 56)
            )

            self.assertEqual(old, "2.0.0")
            self.assertEqual(new, "2.0.1-SNOPSHOT-2026-10-16T12-34-56")
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["version"], new
            )
            self.assertIn(f"- 当前版本：`{new}`", readme_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
