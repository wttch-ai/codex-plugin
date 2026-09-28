#!/usr/bin/env python3
"""准备插件虚拟环境，并运行一个职责单一的运行时脚本。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# Bootstrap 是所有 Hook 的共同入口，因此在这里记录环境准备成功或失败。
from operation_log import record as record_operation, record_runtime
from paths import (
    BOOTSTRAP_LOCK_PATH, PLUGIN_ROOT, REQUIREMENTS_DIGEST_PATH, REQUIREMENTS_PATH,
    RUNTIME_ROOT, VENV_DIGEST_PATH, VENV_PATH,
)


# 保留本地别名，下面的锁逻辑语义更清晰，同时实际路径仍由 paths.py 统一管理。
LOCK_PATH = BOOTSTRAP_LOCK_PATH
LOCK_TIMEOUT_SECONDS = 180
STALE_LOCK_SECONDS = 900


def requirements_digest() -> str:
    """计算依赖清单的内容指纹，用于判断虚拟环境是否需要同步。"""
    return hashlib.md5(REQUIREMENTS_PATH.read_bytes()).hexdigest()


def declared_digest() -> str:
    """验证随插件发布的指纹与实际依赖清单一致并返回该指纹。

    这不是安全用途的哈希，而是发布完整性检查：若两个文件不同，说明依赖清单可能
    已修改但未同步发布指纹，此时不能用不完整的版本更新虚拟环境。
    """
    digest = REQUIREMENTS_DIGEST_PATH.read_text(encoding="utf-8").strip().lower()
    if len(digest) != 32 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError(
            f"invalid dependency digest: path={REQUIREMENTS_DIGEST_PATH} "
            f"value={digest!r}"
        )
    actual = requirements_digest()
    if digest != actual:
        raise RuntimeError(
            "requirement.md5 does not match requirements.txt; "
            f"expected={digest} actual={actual}; "
            "regenerate it before running the plugin"
        )
    return digest


def python_in_venv() -> Path:
    """返回当前平台上虚拟环境解释器的标准位置。"""
    if os.name == "nt":
        return VENV_PATH / "Scripts" / "python.exe"
    return VENV_PATH / "bin" / "python"


def acquire_lock() -> None:
    """获取跨 Hook 的初始化锁，必要时清理由中断进程遗留的过期锁。"""
    VENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    waiting_reported = False
    while True:
        try:
            # mkdir 在同一文件系统中具有原子性，可作为不依赖第三方库的进程锁。
            LOCK_PATH.mkdir()
            (LOCK_PATH / "pid").write_text(str(os.getpid()), encoding="utf-8")
            return
        except FileExistsError:
            if not waiting_reported:
                print("Wttch 环境：正在等待其他 Hook 完成环境准备", file=sys.stderr, flush=True)
                waiting_reported = True
            try:
                age = time.time() - LOCK_PATH.stat().st_mtime
                if age > STALE_LOCK_SECONDS:
                    # 所有者异常退出后不会主动清理锁；超过阈值后允许下一个 Hook 恢复。
                    for child in LOCK_PATH.iterdir():
                        child.unlink()
                    LOCK_PATH.rmdir()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() - started >= LOCK_TIMEOUT_SECONDS:
                raise RuntimeError("timed out waiting for another plugin environment setup")
            time.sleep(0.25)


def release_lock() -> None:
    """释放初始化锁；锁已被其他恢复流程移除时视为成功。"""
    try:
        for child in LOCK_PATH.iterdir():
            child.unlink()
        LOCK_PATH.rmdir()
    except FileNotFoundError:
        pass


def ensure_environment(expected_digest: str) -> Path:
    """创建或同步共享虚拟环境，并在成功后记录已安装依赖的指纹。"""
    interpreter = python_in_venv()
    needs_creation = not interpreter.is_file()
    installed_digest = ""
    if not needs_creation and VENV_DIGEST_PATH.is_file():
        installed_digest = VENV_DIGEST_PATH.read_text(encoding="utf-8").strip().lower()

    if needs_creation:
        print("Wttch 环境：正在创建 Python 虚拟环境", file=sys.stderr, flush=True)
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_PATH)],
            check=True,
            # Hook stdout is reserved for the runtime script's JSON response.
            # Virtual-environment setup is diagnostic output, so keep it on
            # stderr even during first-run initialization.
            stdout=sys.stderr,
            stderr=sys.stderr,
        )

    if needs_creation or installed_digest != expected_digest:
        print("Wttch 环境：正在安装或更新 Python 依赖", file=sys.stderr, flush=True)
        subprocess.run(
            [str(interpreter), "-m", "pip", "install", "--requirement", str(REQUIREMENTS_PATH)],
            check=True,
            # pip normally writes installation progress to stdout.  Sending it
            # to stderr prevents it from corrupting a Hook protocol response.
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
        temporary = VENV_DIGEST_PATH.with_suffix(".tmp")
        temporary.write_text(expected_digest + "\n", encoding="utf-8")
        # 只有 pip 成功后才更新指纹；失败时下次 Hook 会重新尝试安装。
        temporary.replace(VENV_DIGEST_PATH)
        print("Wttch 环境：已就绪，依赖已同步", file=sys.stderr, flush=True)
    else:
        print("Wttch 环境：已就绪，复用现有虚拟环境", file=sys.stderr, flush=True)
    return interpreter


def ready_environment(expected_digest: str) -> Path | None:
    """快速检查环境是否可直接复用。

    Hook 高频触发时，解释器和依赖指纹都没有变化就不需要再次获取初始化锁。
    指纹只在依赖安装成功后写入，因此发现指纹一致时可以安全地跳过同步流程；
    任一文件缺失或内容不一致则返回 ``None``，交给完整准备流程修复。
    """
    interpreter = python_in_venv()
    if not interpreter.is_file() or not VENV_DIGEST_PATH.is_file():
        return None
    try:
        installed_digest = VENV_DIGEST_PATH.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    if installed_digest != expected_digest:
        return None
    return interpreter


def report_preparation_failure(hook_event: str | None) -> None:
    """按 Hook 事件协议报告环境准备失败，并保持 Gate 的失败关闭行为。"""
    reason = "Wttch 环境自动准备失败，本次请求已停止；下次请求会自动重试。"
    if hook_event == "SessionStart":
        print(json.dumps({"systemMessage": reason}, ensure_ascii=False))
    elif hook_event in {"UserPromptSubmit", "PreToolUse"}:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def main() -> int:
    """准备环境后，以模块方式执行位于 runtime 目录内的目标脚本。"""
    arguments = sys.argv[1:]
    hook_event: str | None = None
    if arguments[:1] == ["--hook-event"]:
        if len(arguments) < 3:
            raise ValueError("a hook event and runtime script are required")
        hook_event = arguments[1]
        arguments = arguments[2:]
    if not arguments:
        raise ValueError("a runtime script is required")
    runtime = Path(arguments[0]).resolve()
    try:
        # 限制目标脚本范围，防止 Hook 参数被用于执行插件目录外的任意文件。
        relative_runtime = runtime.relative_to(RUNTIME_ROOT).with_suffix("")
    except ValueError as exc:
        raise ValueError("runtime script must be inside the runtime directory") from exc
    if not runtime.is_file():
        raise FileNotFoundError(runtime)

    try:
        print("Wttch 环境：正在检查 Python 环境", file=sys.stderr, flush=True)
        expected_digest = declared_digest()
        # 大多数 Hook 都走这里：依赖未变化时直接复用，避免每次都创建/检查锁目录。
        interpreter = ready_environment(expected_digest)
        if interpreter is None:
            acquire_lock()
            try:
                interpreter = ensure_environment(expected_digest)
            finally:
                release_lock()
    except Exception as exc:
        # 只记录 Hook 类型，不记录事件正文，避免把用户输入写入日志。
        record_operation(
            "environment.prepare",
            result="error",
            details={"hook_event": hook_event, "error": str(exc)},
        )
        # Windows 下 venv/pip 失败时也保留可读诊断信息，便于排查启动环境问题。
        record_runtime(f"environment.prepare error hook_event={hook_event or '-'} error={exc!r}")
        # 环境无法准备时，不能让模型 Gate 静默失效或让用户手动修复环境。
        report_preparation_failure(hook_event)
        return 0

    # 环境已准备好后再记成功事件，确保日志表示目标运行时确实可用。
    record_operation("environment.prepare", details={"hook_event": hook_event})

    module = ".".join(relative_runtime.parts)
    environment = os.environ.copy()
    pythonpath = environment.get("PYTHONPATH", "")
    # 目标脚本以 ``-m`` 执行，显式加入 runtime 根目录以保留包内和共享模块导入。
    environment["PYTHONPATH"] = (
        str(RUNTIME_ROOT)
        if not pythonpath
        else os.pathsep.join((str(RUNTIME_ROOT), pythonpath))
    )
    completed = subprocess.run(
        [str(interpreter), "-m", module, *arguments[1:]],
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
