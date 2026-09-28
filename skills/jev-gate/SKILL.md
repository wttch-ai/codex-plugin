---
name: jev-gate
description: 发现、解释、验证、测试或执行由 OpenRouter 驱动的 JEV 决策及其 YAML 策略。
---

# JEV 决策

JEV 决策文件位于本 skill 的 `decisions/*.yml`。每个文件定义一个
可执行决策，支持三种 JEV 类型：`choice`、`noul`、`score`。其中 `allow`、`deny`、
`review` 是策略动作，不是 JEV 类型。决策文件只定义固定的类型、候选项和提示词；
具体 `question` 在每次执行时由程序输入或 Hook 事件提供。

列出当前项目决策：

```bash
python3 "${PLUGIN_ROOT}/runtime/bootstrap.py" "${PLUGIN_ROOT}/runtime/jev_gate/main.py" jev-decision list
```

执行指定决策时，将 Hook 事件 JSON 通过标准输入传入：

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git status"}}' \
  | python3 "${PLUGIN_ROOT}/runtime/bootstrap.py" "${PLUGIN_ROOT}/runtime/jev_gate/main.py" \
      jev-decision run <decision-name>
```

This is one skill inside the larger Wttch plugin. Use the plugin's shared runtime
instead of adding a separate environment or dependency file to this skill.

1. Read `gate.yml` before changing behavior. Keep it limited to gate policy:
   defaults, matching rules, actions, reasons, and review instructions.
2. Keep model and transport settings out of the policy YAML. Read the API key
   from `wttch-config.yml` in the runtime working directory, field
   `openrouter.api_key`, or from `OPENROUTER_API_KEY` when it is set. Wttch
   plugin Hooks use the event's `cwd`; its ordinary Skill scripts use their
   process working directory. Read model and transport settings from
   `JEV_OPENROUTER_MODEL`, `JEV_OPENROUTER_BASE_URL`, and
   `JEV_OPENROUTER_TIMEOUT`.
3. Validate the policy with:

   ```bash
   python3 "${PLUGIN_ROOT}/runtime/bootstrap.py" "${PLUGIN_ROOT}/runtime/jev_gate/main.py" validate-jev-policy --policy "${PLUGIN_ROOT}/skills/jev-gate/gate.yml"
   ```

4. Dry-run the hook by piping one `PreToolUse` JSON event into `jev-gate` on the
   same runtime. Never print or echo `OPENROUTER_API_KEY`.
5. Explain which rule matched, whether the outcome was static or reviewed by
   JEV, and whether fail-open behavior was used.
6. Order specific deny or review rules before broad allow rules. Use `deny` for
   deterministic prohibitions, `review` for contextual judgment, and `allow`
   only for clearly safe classes.
