---
name: jev-gate
description: 创建、发现、解释、验证、测试或执行由 OpenRouter 驱动的 JEV 决策及其 YAML Hook 适配。
---

# JEV 决策

本 Skill 的 `example/*.yml` 只用于查看和复制，不是已安装决策，也不能被运行时列出
或按名称执行。项目可执行决策只放在 `.agents/wttch/jev-decisions/*.yml`，支持三种
JEV 类型：`choice`、`noul`、`score`。其中 `allow`、`deny`、
`uncertain` 是 `noul` 的概率分支，`allow`、`warn`、`block` 是 Hook 动作；它们都不是
JEV 类型。决策文件只定义固定的类型、候选项和提示词；
具体 `question` 在每次执行时由程序输入或 Hook 事件提供。
项目决策声明 `hook.user_prompt_submit` 后，只要插件的 JEV UserPromptSubmit Hook 已启用，
统一入口就会自动发现并执行它。所有 JEV 行为都通过项目决策 YAML
定义，不再维护独立的 PreToolUse 策略文件。

声明 `hook.user_prompt_submit` 的决策必须在顶层提供非空 `name`。该名称会显示在最终的
`JEV[名称] 判决结果` 提示中。Hook 运行中的 `statusMessage` 由 Codex 在启动前显示，
无法读取项目 YAML，因此固定为“正在 JEV 判决中…”。

用户要求查看示例时，读取 `example/*.yml` 并说明其字段；不要把示例描述成当前可用
决策。用户要求启用某个示例时，先将其复制到目标项目的
`.agents/wttch/jev-decisions/`，再按项目需求修改。

## 创建项目决策

1. 将最接近需求的 `example/*.yml` 复制到目标项目的
   `.agents/wttch/jev-decisions/<decision-name>.yml`。不要直接修改或启用插件示例。
2. 将判断目标写成一个正向、可回答真假的 `noul` 问题。例如要区分编排器代码和业务
   代码，应询问“该请求是否只维护当前编排器项目”，而不是含糊地询问“这是什么任务”。
3. 在 `criteria.true` 和 `criteria.false` 中写清边界，并让
   `hook.user_prompt_submit.question` 引用该 `noul` 问题。
4. 在顶层添加简短的 `name`，用于识别此自动判决。
5. 用 `allow_at_or_above` 和 `uncertain_at_or_above` 将概率划分为 `allow`、
   `uncertain`、`deny` 三个分支。每个分支分别配置 `action` 和非空 `message`；
   `action` 可取 `allow`、`warn` 或 `block`。
6. `warn` 会让请求继续并把 `message` 注入当前 Agent。若需模型先询问用户，应直接在
   `message` 中写入明确的提示词：先检查当前对话是否已有针对该问题的明确答复；有则
   依照答复继续、不要重复提问；没有才询问用户，且确认前不要执行相关操作。只有必须
   协议级禁止继续时才使用 `block`。需要真正自动调度时，应实现专用 Hook 适配器。
7. 一个项目最多只能有一个声明 `hook.user_prompt_submit` 的决策。普通的手动决策可以有
   多个，但不要声明该 Hook。

## 会话连续性路由

`UserPromptSubmit` 内置记录同一项目、同一会话最近的原始用户输入到
`~/.wttch/jev-history/`。在主决策的 `hook.user_prompt_submit` 中可选声明 `continuity`，
用另一个已定义的项目 JEV 判断本轮是上文的连续回答还是新请求：

```yaml
continuity:
  max_messages: 8
  decision: conversation-continuity
  question: relationship
  routes:
    continuation:
      action: skip
      message: "这是对上文的连续回答；跳过主 Gate，并结合上文继续处理。"
    new_request:
      action: primary
```

连续性决策必须返回 `choice`，其候选值对应 `routes` 的键。路由动作为：`skip`（跳过主
Gate）、`primary`（继续主 Gate）、`decision`（运行 `decision` 字段引用的另一个已定义
项目 JEV，并把结果注入当前对话）。`max_messages` 为 1–100。历史按项目与会话隔离，
文件名不包含原始会话 ID；原始输入会被本机持久化，启用前应取得用户授权。

编排器项目的创建与路由示例位于 `example/orchestrator-routing.yml`。复制后，将示例中的
`business-code-agent` 替换为该编排器项目实际提供的 Agent 名称。

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
