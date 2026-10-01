"""Wttch Hook 面向用户的提示格式。"""

from __future__ import annotations


def hook_notice(detail: str) -> str:
    """说明提示来自已安装的 Wttch 插件，并保留具体原因。"""
    return f"你安装了 Wttch 插件，但是{detail}"
