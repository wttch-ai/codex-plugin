---
name: git-commit
description: 智能 Git 提交工具。自动分析代码变更，生成结构化 commit message，支持多功能的分类描述。触发关键词：提交、commit、git提交。
---

# Git 智能提交

## 提交类型

根据变更选择 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`chore` 或 `revert`。

## 工作流程

1. 用 `git status` 和 `git diff` 分析变更文件、功能模块和提交类型。
2. 生成结构化 message：单功能为 `<type>: <一句话描述>`；独立功能应拆分提交。
3. 必须先向用户展示文件列表、变更类型和拟提交 message，并取得明确确认后才执行 `git commit`。

不得使用 `--auto`、`--no-verify` 或其他跳过用户确认的方式。避免在同一提交中混入无关变更。
