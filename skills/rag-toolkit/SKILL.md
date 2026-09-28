---
name: rag-toolkit
description: 在当前项目的本地 RAG 记忆库中检索、导入文档、沉淀可复用结论或维护 RAG API。用于 RAG 检索、记忆保存、RAG 入库、架构决策与接口契约回溯。
---

# 项目本地 RAG

本 skill 的代码与依赖由插件提供；数据库绝不写入插件目录。每个调用项目在自己的工作目录下保存：

```text
.agents/wttch/rag-data/rag.db
```

项目 scope 位于 `.agents/wttch/rag-scope.yml`，它是 `key`、`description` 的列表。`key` 用于 `--scope`，`description` 说明该 scope 的知识边界：

```yaml
- key: project
  description: 当前项目的通用知识与约束
```

从项目根目录调用插件运行时（`PLUGIN_ROOT` 指插件安装目录）：

```bash
python "${PLUGIN_ROOT}/runtime/rag_toolkit/rag.py" <command>
```

查看当前项目可识别的 scope：

```bash
python "${PLUGIN_ROOT}/runtime/rag_toolkit/rag.py" scopes
```

- 遇到历史决策、陌生链路、项目契约或难以定位的问题时先执行 `query`。
- 仅把架构决策、唯一契约、关键修复和可复用经验以 `memorize` 保存；普通文案和一次性小改动不入库。
- 数据库只能经 `rag.py` 的命令读写，禁止直接访问 `.agents/wttch/rag-data/rag.db`。
- 项目自己的 `AGENTS.md` 负责约束哪些内容应沉淀、保留或清除；RAG 不在项目之间共享数据。
- 写入、导入和检索时使用 `--scope <key>`；scope 必须在 `rag-scope.yml` 中声明。

为避免提交本地记忆库，使用方项目应包含：

```gitignore
.agents/wttch/rag-data/*.db
.agents/wttch/rag-data/*.db-*
```

命令和参数以 `rag.py help <command>` 为准；RAG 仅通过 CLI 提供能力，不启动独立 server。