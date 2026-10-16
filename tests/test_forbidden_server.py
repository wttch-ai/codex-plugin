import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import forbidden_server  # noqa: E402
import paths  # noqa: E402
import runner  # noqa: E402


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
        self.assertNotIn("permissionDecision", result["hookSpecificOutput"])
        self.assertIn("additionalContext", result["hookSpecificOutput"])

    def test_block_precedes_warn(self) -> None:
        result = forbidden_server.evaluate({"cwd": str(self.root), "tool_input": {"command": "curl prod.example; ssh 192.168.2.29"}})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")


class RuntimeBootstrapTests(unittest.TestCase):
    def test_shared_runtime_location(self) -> None:
        self.assertEqual(paths.RUNTIME_VENV, Path.home() / ".wttch" / "agent-runtime" / "venv")

    def test_runtime_python_path(self) -> None:
        venv = Path("runtime") / ".venv"
        self.assertEqual(runner.runtime_python_path(venv, "nt"), venv / "Scripts" / "python.exe")
        self.assertEqual(runner.runtime_python_path(venv, "posix"), venv / "bin" / "python")

    def test_system_python_delegates_to_runtime(self) -> None:
        runtime_python = Path("runtime-python")
        completed = type("Completed", (), {"returncode": 7})()
        with (
            patch.object(sys, "prefix", str(Path.home() / "system-python")),
            patch.object(runner, "runtime_python_path", return_value=runtime_python),
            patch.object(Path, "is_file", return_value=True),
            patch.object(runner.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(
                runner.main(
                    [
                        "--mode",
                        "run",
                        "--hook-event",
                        "PreToolUse",
                        "target.py",
                        "argument",
                    ]
                ),
                7,
            )
        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [
                str(runtime_python),
                str(Path(runner.__file__).resolve()),
                "--mode",
                "run",
                "--hook-event",
                "PreToolUse",
                "target.py",
                "argument",
            ],
        )

    def test_prepare_uses_virtualenv_pip(self) -> None:
        runtime_python = Path("runtime-python")
        completed = type("Completed", (), {"returncode": 0})()
        with (
            patch.object(runner, "runtime_python_path", return_value=runtime_python),
            patch.object(Path, "is_file", return_value=True),
            patch.object(runner.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(runner.prepare_runtime(), 0)
        self.assertEqual(
            run.call_args.args[0],
            [
                str(runtime_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(paths.PLUGIN_ROOT / "requirements.txt"),
            ],
        )

    def test_prepare_creates_venv_with_local_python(self) -> None:
        runtime_python = Path("runtime-python")
        completed = type("Completed", (), {"returncode": 0})()
        with (
            patch.object(runner, "runtime_python_path", return_value=runtime_python),
            patch.object(Path, "is_file", return_value=False),
            patch.object(runner.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(runner.main(["--mode", "prepare"]), 0)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [sys.executable, "-m", "venv", str(paths.RUNTIME_VENV)],
        )
        self.assertEqual(run.call_args_list[1].args[0][0], str(runtime_python))

    def test_reinstall_forces_dependency_reinstall(self) -> None:
        runtime_python = Path("runtime-python")
        completed = type("Completed", (), {"returncode": 0})()
        with (
            patch.object(runner, "runtime_python_path", return_value=runtime_python),
            patch.object(Path, "is_file", return_value=True),
            patch.object(runner.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(runner.main(["--mode", "reinstall"]), 0)
        self.assertEqual(run.call_args.args[0][-1], "--force-reinstall")


if __name__ == "__main__":
    unittest.main()
