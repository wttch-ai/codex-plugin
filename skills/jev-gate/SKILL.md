---
name: jev-gate
description: 发现、解释、验证、测试或执行由 OpenRouter 驱动的 JEV 决策及其 YAML 策略。
---

# JEV 决策

本 Skill 的 `example/*.yml` 只用于查看和复制，不是已安装决策，也不能被运行时列出
或按名称执行。项目可执行决策只放在 `.agents/wttch/jev-decisions/*.yml`，支持三种
JEV 类型：`choice`、`noul`、`score`。其中 `allow`、`deny`、
`review` 是策略动作，不是 JEV 类型。决策文件只定义固定的类型、候选项和提示词；
具体 `question` 在每次执行时由程序输入或 Hook 事件提供。
项目决策声明 `hook.user_prompt_submit` 后，只要插件的 JEV UserPromptSubmit Hook 已启用，
统一入口就会自动发现并执行它。所有 JEV 行为都通过项目决策 YAML
定义，不再维护独立的 PreToolUse 策略文件。

用户要求查看示例时，读取 `example/*.yml` 并说明其字段；不要把示例描述成当前可用
决策。用户要求启用某个示例时，先将其复制到目标项目的
`.agents/wttch/jev-decisions/`，再按项目需求修改。

列出当前项目决策：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode run "${PLUGIN_ROOT}/runtime/jev/main.py" decision list
```

执行指定决策时，将 Hook 事件 JSON 通过标准输入传入：

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git status"}}' \
python "${PLUGIN_ROOT}/runtime/runner.py" --mode run "${PLUGIN_ROOT}/runtime/jev/main.py" \
  decision run <decision-name> <<'JSON'
{"state":"本次执行的动态输入"}
JSON
```

This is one skill inside the larger Wttch plugin. Use the plugin's shared runtime
instead of adding a separate environment or dependency file to this skill.

1. Keep the model and questions in each decision YAML. Pass dynamic state through stdin;
   do not write request-specific state into the definition.
2. Read the API key and Decisions API settings only from the current project's
   `.agents/wttch/config.yml`. Never print or echo `openrouter.api_key`.
3. Put automatic Hook routing under the decision's top-level `hook` object. The runtime
   currently supports `hook.user_prompt_submit` and rejects unknown adapters.
4. Copy an example into `.agents/wttch/jev-decisions/` before enabling it.
   Files under `example/` must remain undiscoverable and inactive.
5. Validate a changed definition by loading it through `jev.decision.load_decision`, then
   test its probability thresholds and Hook output mappings.
