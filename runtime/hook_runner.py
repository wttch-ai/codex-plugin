#!/usr/bin/env python3
"""运行 Hook 目标，并将缺依赖或运行异常降级为非阻断警告。"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


def warning(hook_event: str, error: Exception) -> dict[str, object]:
    message = f"Wttch Hook 未执行：{error}。请在插件根目录运行 uv sync 以准备依赖。"
    if hook_event == "UserPromptSubmit":
        return {
            "systemMessage": message,
            "hookSpecificOutput": {"hookEventName": hook_event, "additionalContext": message},
        }
    if hook_event == "PreToolUse":
        return {"hookSpecificOutput": {"hookEventName": hook_event, "additionalContext": message}}
    return {"systemMessage": message}


def main() -> int:
    if len(sys.argv) < 3:
        raise ValueError("usage: hook_runner.py <HookEvent> <target.py> [args...]")
    hook_event, target, *arguments = sys.argv[1:]
    try:
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
