#!/usr/bin/env python3
"""Prepare the plugin environment and run plugin Python entry points in it."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from notice import hook_notice
from operation_log import record_runtime
from paths import PLUGIN_ROOT, RUNTIME_VENV
from wttch_logging import log_path, log_root


def runtime_python_path(venv: Path = RUNTIME_VENV, platform: str = os.name) -> Path:
    """Return the Python executable inside the shared plugin environment."""
    if platform == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def prepare_command(mode: str = "prepare") -> str:
    """Return a safe environment maintenance command for user-facing errors."""
    return f'python "{Path(__file__).resolve()}" --mode {mode}'


def prepare_runtime(reinstall: bool = False) -> int:
    """Create or update the persistent plugin environment using local Python."""
    RUNTIME_VENV.parent.mkdir(parents=True, exist_ok=True)
    runtime_python = runtime_python_path()
    if not runtime_python.is_file():
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(RUNTIME_VENV)],
            check=False,
        )
        if created.returncode != 0:
            record_runtime(f"创建插件虚拟环境失败，退出码 {created.returncode}")
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
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        record_runtime(f"安装插件依赖失败，退出码 {completed.returncode}")
    return completed.returncode


def runtime_status() -> dict[str, object]:
    """Return safe runtime and logging metadata without requiring the venv."""
    runtime_python = runtime_python_path()
    current_log = log_path()
    return {
        "runtime": {
            "root": str(RUNTIME_VENV.parent),
            "virtual_environment": str(RUNTIME_VENV),
            "python": str(runtime_python),
            "ready": runtime_python.is_file(),
            "requirements": str(PLUGIN_ROOT / "requirements.txt"),
        },
        "logging": {
            "directory": str(log_root()),
            "current_file": str(current_log),
            "current_file_exists": current_log.is_file(),
            "format": "json-lines",
            "console_output": False,
        },
    }


def hook_warning(hook_event: str, error: Exception) -> dict[str, object]:
    """Build a non-blocking Codex Hook response."""
    message = hook_notice(
        f"Wttch Hook 未执行：{error}。请使用本地 Python 运行 "
        f"{prepare_command()} 以准备依赖。"
    )
    if hook_event == "UserPromptSubmit":
        return {
            "systemMessage": message,
            "hookSpecificOutput": {
                "hookEventName": hook_event,
                "additionalContext": message,
            },
        }
    if hook_event == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": hook_event,
                "additionalContext": message,
            }
        }
    return {"systemMessage": message}


def run_target(target: str, arguments: Sequence[str], hook_event: str | None = None) -> int:
    """Run a plugin entry point inside the shared environment."""
    try:
        runtime_python = runtime_python_path()
        if Path(sys.prefix).resolve() != RUNTIME_VENV.resolve():
            if not runtime_python.is_file():
                raise FileNotFoundError(f"未找到插件运行环境 {runtime_python}")
            command = [
                str(runtime_python),
                str(Path(__file__).resolve()),
                "--mode",
                "run",
            ]
            if hook_event:
                command.extend(["--hook-event", hook_event])
            command.extend([target, *arguments])
            return subprocess.run(command, check=False).returncode

        sys.argv = [target, *arguments]
        runpy.run_path(str(Path(target).resolve()), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    except Exception as exc:
        record_runtime(f"执行 {target} 失败：{type(exc).__name__}: {exc}")
        if hook_event:
            print(json.dumps(hook_warning(hook_event, exc), ensure_ascii=True))
            return 0
        print(f"Wttch runtime 执行失败：{exc}", file=sys.stderr)
        print(f"请使用本地 Python 运行 {prepare_command()}。", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="创建、更新或使用 Wttch 插件的共享 Python 环境。"
    )
    parser.add_argument(
        "--mode",
        choices=("prepare", "reinstall", "status", "run"),
        required=True,
        help="prepare 更新依赖，reinstall 强制重装，status 查看状态，run 执行入口。",
    )
    parser.add_argument(
        "--hook-event",
        choices=("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"),
        help="仅 Hook 使用；发生异常时输出对应的非阻断 Hook 响应。",
    )
    parser.add_argument("target", nargs="?", help="run 模式要执行的 Python 文件。")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="传递给目标文件的参数。")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "prepare":
        if args.target or args.arguments or args.hook_event:
            raise ValueError("prepare 模式不接受目标文件、目标参数或 Hook 事件")
        return prepare_runtime()
    if args.mode == "reinstall":
        if args.target or args.arguments or args.hook_event:
            raise ValueError("reinstall 模式不接受目标文件、目标参数或 Hook 事件")
        return prepare_runtime(reinstall=True)
    if args.mode == "status":
        if args.target or args.arguments or args.hook_event:
            raise ValueError("status 模式不接受目标文件、目标参数或 Hook 事件")
        print(json.dumps(runtime_status(), ensure_ascii=False, indent=2))
        return 0
    if not args.target:
        raise ValueError("run 模式需要目标 Python 文件")
    return run_target(args.target, args.arguments, args.hook_event)


if __name__ == "__main__":
    raise SystemExit(main())
