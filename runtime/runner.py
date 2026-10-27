#!/usr/bin/env python3
"""准备共享 Python 环境并统一启动插件 Skill/Hook 入口。

runner 必须能由用户机器上的本地 Python 直接启动，因此本文件及其顶层导入只能依赖
Python 标准库和插件自身的轻量模块。``prepare``/``reinstall`` 负责维护
``~/.wttch/agent-runtime/venv``；``run`` 先从本地 Python 转交到该环境，再执行目标脚本；
``status`` 在环境损坏或尚未创建时仍可报告安全元数据。

Hook 模式发生异常时必须输出合法协议响应，不能输出 traceback；非 Hook CLI 才允许把
错误摘要写入 stderr。所有详细诊断通过 ``wttch_logging`` 进入仅文件日志。
"""

from __future__ import annotations

import argparse
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from hooks import UserPromptSubmitOutput
from notice import hook_notice
from paths import PLUGIN_ROOT, RUNTIME_VENV
from wttch_logging import jev_log_path, log_path, log_root, record_runtime


def runtime_python_path(venv: Path = RUNTIME_VENV, platform: str = os.name) -> Path:
    """按平台返回共享虚拟环境内的 Python 可执行文件路径。

    参数允许测试注入环境目录与平台名；生产调用使用 ``~/.wttch/agent-runtime/venv``
    和当前操作系统。这里只计算路径，不探测文件是否存在。
    """
    if platform == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def prepare_command(mode: str = "prepare") -> str:
    """生成可直接展示给用户的环境维护命令。

    使用 runner 的绝对路径，避免 Hook 从任意项目工作目录启动时给出不可执行的相对命令。
    """
    return f'python "{Path(__file__).resolve()}" --mode {mode}'


def prepare_runtime(reinstall: bool = False) -> int:
    """用本地 Python 创建共享 venv，再用 venv 自身的 pip 同步依赖。

    ``reinstall`` 只增加 ``--force-reinstall``，不切换到全局 pip。子进程退出码原样返回；
    失败摘要写入仅文件日志，runner 不吞掉环境准备命令的失败状态。
    """
    RUNTIME_VENV.parent.mkdir(parents=True, exist_ok=True)
    runtime_python = runtime_python_path()
    # 环境不存在时必须使用启动 runner 的本地 Python 创建，不能依赖全局 pip。
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
    """返回无需虚拟环境即可计算的运行时与日志安全元数据。

    状态中不读取配置值、日志内容或凭据，只报告路径、环境是否就绪、文件是否存在、
    日志布局与禁止控制台输出的约束，因此可由本地 Python 在故障排查阶段安全调用。
    """
    runtime_python = runtime_python_path()
    current_log = log_path()
    current_jev_log = jev_log_path()
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
            "jev_current_file": str(current_jev_log),
            "jev_current_file_exists": current_jev_log.is_file(),
            # 该值描述文件布局，不代表运行时依赖 Spring Boot 或 Java。
            "format": "spring-boot",
            "console_output": False,
        },
    }


def hook_warning(
    hook_event: str, error: Exception
) -> UserPromptSubmitOutput | dict[str, object]:
    """把 runner 异常转换为对应 Hook 的非阻断响应。

    UserPromptSubmit 必须返回强类型实体；其他尚未实体化的 Hook 暂用字典。所有响应都会
    告知环境准备命令，但不会包含 traceback、环境变量或可能泄密的完整输入。
    """
    reason = (
        f"Wttch Hook 未执行：{error}。请使用本地 Python 运行 "
        f"{prepare_command()} 以准备依赖。"
    )
    if hook_event == "UserPromptSubmit":
        # 让对话继续，并把异常与面向模型的告警指令一同注入当前请求。
        return UserPromptSubmitOutput.error_warning(reason)
    message = hook_notice(reason)
    if hook_event == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": hook_event,
                "additionalContext": message,
            }
        }
    return {"systemMessage": message}


def run_target(target: str, arguments: Sequence[str], hook_event: str | None = None) -> int:
    """在共享环境中运行插件入口，并保持 Hook 协议通道可用。

    本地 Python 首次调用时会用虚拟环境 Python 再启动 runner；第二阶段检测到
    ``sys.prefix`` 已是目标 venv 后，通过 ``runpy`` 在同一进程执行目标脚本。Hook
    失败被转换为协议响应并返回 0，避免宿主丢弃提示；普通 CLI 失败则写 stderr 并返回 1。
    """
    try:
        runtime_python = runtime_python_path()
        # 首次由本地 Python 启动时转交给共享环境；环境内再次执行时直接运行目标。
        if Path(sys.prefix).resolve() != RUNTIME_VENV.resolve():
            if not runtime_python.is_file() and prepare_runtime() != 0:
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
        # 日志失败不得覆盖原始错误，也不得把诊断信息写入 Hook 协议通道。
        record_runtime(f"执行 {target} 失败：{type(exc).__name__}: {exc}")
        if hook_event:
            warning = hook_warning(hook_event, exc)
            if isinstance(warning, UserPromptSubmitOutput):
                print(warning.dump_json())
            else:
                print(json.dumps(warning, ensure_ascii=True))
            return 0
        print(f"Wttch runtime 执行失败：{exc}", file=sys.stderr)
        print(f"请使用本地 Python 运行 {prepare_command()}。", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """定义环境维护、状态查询和入口执行四种互斥模式。"""
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
    """校验各模式参数并执行对应的环境或入口操作。"""
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
