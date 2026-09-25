#!/usr/bin/env python3
"""准备插件虚拟环境，并运行一个职责单一的运行时脚本。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PLUGIN_ROOT / "runtime"
REQUIREMENTS_PATH = PLUGIN_ROOT / "requirements.txt"
REQUIREMENTS_DIGEST_PATH = PLUGIN_ROOT / "requirement.md5"
VENV_PATH = PLUGIN_ROOT / ".venv"
VENV_DIGEST_PATH = VENV_PATH / "requirement.md5"
LOCK_PATH = VENV_PATH.with_name(".venv.bootstrap.lock")
LOCK_TIMEOUT_SECONDS = 180
STALE_LOCK_SECONDS = 900


def requirements_digest() -> str:
    return hashlib.md5(REQUIREMENTS_PATH.read_bytes()).hexdigest()


def declared_digest() -> str:
    digest = REQUIREMENTS_DIGEST_PATH.read_text(encoding="utf-8").strip().lower()
    if len(digest) != 32 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeError(f"invalid dependency digest: {REQUIREMENTS_DIGEST_PATH}")
    actual = requirements_digest()
    if digest != actual:
        raise RuntimeError(
            "requirement.md5 does not match requirements.txt; "
            "regenerate it before running the plugin"
        )
    return digest


def python_in_venv() -> Path:
    if os.name == "nt":
        return VENV_PATH / "Scripts" / "python.exe"
    return VENV_PATH / "bin" / "python"


def acquire_lock() -> None:
    VENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    waiting_reported = False
    while True:
        try:
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
    try:
        for child in LOCK_PATH.iterdir():
            child.unlink()
        LOCK_PATH.rmdir()
    except FileNotFoundError:
        pass


def ensure_environment(expected_digest: str) -> Path:
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
        )

    if needs_creation or installed_digest != expected_digest:
        print("Wttch 环境：正在安装或更新 Python 依赖", file=sys.stderr, flush=True)
        subprocess.run(
            [str(interpreter), "-m", "pip", "install", "--requirement", str(REQUIREMENTS_PATH)],
            check=True,
        )
        temporary = VENV_DIGEST_PATH.with_suffix(".tmp")
        temporary.write_text(expected_digest + "\n", encoding="utf-8")
        temporary.replace(VENV_DIGEST_PATH)
        print("Wttch 环境：已就绪，依赖已同步", file=sys.stderr, flush=True)
    else:
        print("Wttch 环境：已就绪，复用现有虚拟环境", file=sys.stderr, flush=True)
    return interpreter


def main() -> int:
    if len(sys.argv) < 2:
        raise ValueError("a runtime script is required")
    runtime = Path(sys.argv[1]).resolve()
    try:
        relative_runtime = runtime.relative_to(RUNTIME_ROOT).with_suffix("")
    except ValueError as exc:
        raise ValueError("runtime script must be inside the runtime directory") from exc
    if not runtime.is_file():
        raise FileNotFoundError(runtime)

    print("Wttch 环境：正在检查 Python 环境", file=sys.stderr, flush=True)
    expected_digest = declared_digest()
    acquire_lock()
    try:
        interpreter = ensure_environment(expected_digest)
    finally:
        release_lock()

    module = ".".join(relative_runtime.parts)
    environment = os.environ.copy()
    pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(RUNTIME_ROOT)
        if not pythonpath
        else os.pathsep.join((str(RUNTIME_ROOT), pythonpath))
    )
    completed = subprocess.run(
        [str(interpreter), "-m", module, *sys.argv[2:]],
        env=environment,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
