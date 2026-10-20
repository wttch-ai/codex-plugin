"""本地持久化 UserPromptSubmit 的最近用户输入。

记录按会话隔离，默认写入 ``~/.wttch/jev-history``。内容是用户明确授权保留的原始
输入，只供 JEV 连续性判决使用；文件名使用 session id 的 SHA-256 摘要，避免在目录
列表中暴露会话标识。环境变量仅用于测试隔离。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from paths import JEV_HISTORY_ROOT


def history_root() -> Path:
    """返回会话历史目录；测试可通过环境变量隔离磁盘写入。"""
    override = os.environ.get("WTTCH_JEV_HISTORY_DIR", "").strip()
    return Path(override).expanduser() if override else JEV_HISTORY_ROOT


def session_history_path(session_id: str) -> Path:
    """返回会话对应的固定历史文件路径，不在文件名中保存原始 session id。"""
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return history_root() / f"{digest}.json"


def recent_prompts(session_id: str, limit: int) -> list[str]:
    """读取本会话最近 ``limit`` 条输入；损坏或不存在的记录按空历史处理。"""
    if limit < 1:
        raise ValueError("history limit must be positive")
    try:
        data = json.loads(session_history_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    prompts = data.get("prompts") if isinstance(data, dict) else None
    if not isinstance(prompts, list) or not all(isinstance(prompt, str) for prompt in prompts):
        return []
    return prompts[-limit:]


def append_prompt(session_id: str, prompt: str, limit: int) -> list[str]:
    """追加原始输入并原子写回，返回追加前的最近输入。

    同一会话通常串行提交；原子替换保证崩溃时不会留下半写 JSON。存储上限由当前项目
    决策配置决定，历史文件不会无限增长。
    """
    previous = recent_prompts(session_id, limit)
    path = session_history_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "prompts": [*previous, prompt]}, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}.", delete=False
        ) as stream:
            stream.write(payload)
            temporary = Path(stream.name)
        temporary.replace(path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
    return previous
