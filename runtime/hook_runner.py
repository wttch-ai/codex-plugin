#!/usr/bin/env python3
"""运行 Hook 目标，并将缺依赖或运行异常降级为非阻断警告。"""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

from notice import hook_notice
from paths import PLUGIN_ROOT, RUNTIME_VENV


def runtime_python_path(venv: Path = RUNTIME_VENV, platform: str = os.name) -> Path:
    """返回共享运行环境中的 Python 路径。"""
    if platform == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def prepare_command() -> str:
    """返回不会泄露配置值的环境准备提示。"""
    return f'python "{Path(__file__).resolve()}" --prepare'


def prepare_runtime(reinstall: bool = False) -> int:
    """将插件依赖同步到独立于插件缓存的共享虚拟环境。"""
    RUNTIME_VENV.parent.mkdir(parents=True, exist_ok=True)
    runtime_python = runtime_python_path()
    if not runtime_python.is_file():
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(RUNTIME_VENV)],
            check=False,
        )
        if created.returncode != 0:
            return created.returncode
    command = [
        str(runtime_python),
        "-m",
        "pip",
        "install",
        "-r",
        str(PLUGIN_ROOT / "requirements.txt"),
    ]
    if reinstall:
        command.append("--force-reinstall")
    return subprocess.run(command, check=False).returncode


def warning(hook_event: str, error: Exception) -> dict[str, object]:
    message = hook_notice(
        f"Wttch Hook 未执行：{error}。请使用系统默认 Python 运行 {prepare_command()} 以准备依赖。"
    )
    if hook_event == "UserPromptSubmit":
        return {
            "systemMessage": message,
            "hookSpecificOutput": {"hookEventName": hook_event, "additionalContext": message},
        }
    if hook_event == "PreToolUse":
        return {"hookSpecificOutput": {"hookEventName": hook_event, "additionalContext": message}}
    return {"systemMessage": message}


def main() -> int:
    if sys.argv[1:] in (["--prepare"], ["--prepare", "--reinstall"]):
        return prepare_runtime(reinstall="--reinstall" in sys.argv[1:])
    if len(sys.argv) < 3:
        raise ValueError(
            "usage: hook_runner.py --prepare [--reinstall] | "
            "hook_runner.py <HookEvent> <target.py> [args...]"
        )
    hook_event, target, *arguments = sys.argv[1:]
    try:
        runtime_python = runtime_python_path()
        if Path(sys.prefix).resolve() != RUNTIME_VENV.resolve():
            if not runtime_python.is_file():
                raise FileNotFoundError(f"未找到共享运行环境 {runtime_python}")
            completed = subprocess.run(
                [str(runtime_python), str(Path(__file__).resolve()), hook_event, target, *arguments],
                check=False,
            )
            return completed.returncode
        sys.argv = [target, *arguments]
        runpy.run_path(str(Path(target).resolve()), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    except Exception as exc:
        print(json.dumps(warning(hook_event, exc), ensure_ascii=True))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
