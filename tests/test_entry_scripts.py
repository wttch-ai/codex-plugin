"""Regression checks for the system-Python launcher scripts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MISSING_PYTHON = r"\u672c\u673a\u672a\u5b89\u88c5 Python"


class EntryScriptTests(unittest.TestCase):
    def test_hooks_use_extensionless_platform_launcher(self) -> None:
        manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for groups in manifest["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertTrue(commands)
        self.assertTrue(all('"${PLUGIN_ROOT}/runtime/bootstrap"' in command for command in commands))
        windows_commands = [
            hook["commandWindows"]
            for groups in manifest["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertTrue(
            all('powershell.exe ' in command for command in windows_commands)
        )
        self.assertTrue(
            all('"${PLUGIN_ROOT}/runtime/bootstrap.ps1"' in command for command in windows_commands)
        )
        self.assertFalse(any("python3" in command for command in commands))

    def test_posix_launcher_only_checks_system_python(self) -> None:
        launcher = (ROOT / "runtime" / "bootstrap").read_text(encoding="utf-8")
        self.assertIn("command -v python3", launcher)
        self.assertIn("command -v python", launcher)
        self.assertNotIn('runtime_python=', launcher)
        self.assertIn('exec "$python_command" "$script_dir/runner.py" "$@"', launcher)
        self.assertIn(MISSING_PYTHON, launcher)

    def test_windows_launcher_only_checks_system_python(self) -> None:
        launcher = (ROOT / "runtime" / "bootstrap.cmd").read_text(encoding="utf-8")
        self.assertIn("where python", launcher)
        self.assertIn("where python3", launcher)
        self.assertNotIn("RUNTIME_PYTHON", launcher)
        self.assertIn('"%PYTHON_COMMAND%" "%SCRIPT_DIR%runner.py" %*', launcher)
        self.assertIn(MISSING_PYTHON, launcher)

    def test_windows_hook_launcher_supports_missing_python(self) -> None:
        launcher = (ROOT / "runtime" / "bootstrap.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-Command python", launcher)
        self.assertIn("Get-Command python3", launcher)
        self.assertIn("Get-Command py", launcher)
        self.assertIn("hookSpecificOutput", launcher)
        self.assertIn("exit 0", launcher)
        self.assertNotIn("RUNTIME_PYTHON", launcher)
        self.assertIn("Python is not installed", launcher)


if __name__ == "__main__":
    unittest.main()
