#!/usr/bin/env python3
"""JEV 项目决策与 Hook 的统一命令行入口。

``decision list/run`` 面向 Skill 和人工调试，只发现项目
``.agents/wttch/jev-decisions`` 中显式安装的决策；``hook user-prompt-submit`` 面向
Codex Hook，自动寻找唯一绑定的项目决策。插件 ``example`` 目录不属于运行时搜索路径，
因此安装插件本身不会启用任何示例策略。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Support both ``python runtime/jev/main.py`` and package imports in tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev.decision import list_decisions, run_named_decision, run_user_prompt_submit_hook


def build_parser() -> argparse.ArgumentParser:
    """构建统一的 decision 与 hook 子命令树。

    采用两级子命令而不是多个入口文件，使 Skill 手动执行与 Hook 自动执行共享同一套
    决策加载、配置和网络请求实现。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    decision = commands.add_parser("decision", help="发现或执行 JEV 决策。")
    decision_commands = decision.add_subparsers(dest="decision_command", required=True)
    decision_commands.add_parser("list", help="列出内置和项目级决策。")
    decision_run = decision_commands.add_parser("run", help="执行指定决策。")
    decision_run.add_argument("name")

    hook = commands.add_parser("hook", help="执行 Codex Hook。")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    hook_commands.add_parser("user-prompt-submit", help="执行 UserPromptSubmit 决策。")
    return parser


def main(argv: list[str] | None = None) -> int:
    """将解析后的命令分派到列表、手动执行或 UserPromptSubmit 处理器。"""
    args = build_parser().parse_args(argv)
    if args.command == "decision":
        if args.decision_command == "list":
            return list_decisions()
        return run_named_decision(args.name)

    return run_user_prompt_submit_hook()


if __name__ == "__main__":
    raise SystemExit(main())
