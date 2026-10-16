---
name: project-commit
description: 管理 wttch-codex-plugin 仓库的 Git 提交。当用户要求提交、commit、git 提交或保存本项目代码时使用；提交前必须刷新插件 SNOPSHOT 版本号。仅适用于当前仓库，不是随插件分发的 Skill。
---

# Project Commit

只管理 `wttch-codex-plugin` 当前仓库。不要将本 Skill 当作插件能力，也不要复制到仓库的
`skills/` 目录。

## 提交流程

1. 用 `git rev-parse --show-toplevel` 确认仓库根目录，并确认根目录中同时存在
   `.codex-plugin/plugin.json` 和 `README.md`。不满足时停止，不要修改其他仓库。
2. 检查 `git status --short`、未暂存和已暂存差异，保留用户已有变更，不混入无关文件。
3. 根据改动风险运行相应测试，并执行 `git diff --check`。
4. 在所有检查通过后、执行 `git add` 之前，从仓库根目录运行：

   ```bash
   python .agents/skills/project-commit/scripts/update_snapshot_version.py
   ```

5. 确认 `.codex-plugin/plugin.json` 与 README 的版本一致，版本形式为
   `MAJOR.MINOR.PATCH-SNOPSHOT-YYYY-MM-DDTHH-mm-ss`。
6. 暂存本次提交需要的文件，再次检查 `git diff --cached --check` 和暂存摘要，然后创建提交。
7. 报告 commit hash、message、测试结果以及工作区是否干净。除非用户明确要求，不推送远端。

## 版本规则

- 当前版本已经是 `SNOPSHOT` 时，保留 `MAJOR.MINOR.PATCH`，只更新时间戳。
- 当前版本是稳定 SemVer 或只有构建元数据时，将 PATCH 加一后进入 `SNOPSHOT`。
- 时间使用本机当前时间；脚本保证新时间戳严格晚于已有快照时间，连续提交也会产生新版本。
- 必须保留项目约定的 `SNOPSHOT` 拼写，不要自动改成 `SNAPSHOT`。
- 不要手工只改一个文件；始终使用脚本同步插件清单和 README。

## 提交信息

根据变更选择 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`chore`
或 `revert`。单一功能使用 `<type>: <简短说明>`；只有在变更确实彼此独立时才拆分提交。
