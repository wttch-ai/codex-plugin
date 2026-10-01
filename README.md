# Wttch Codex Plugin

Wttch 的私人 Codex 插件，用来集中维护可复用的 Skills、生命周期 Hooks、
策略文件和共享 Python 运行时。

- 主页：<https://wttch.com>
- 插件名称：`wttch-codex-plugin`
- 当前版本：`0.1.43`
- 使用范围：私人插件

## 快速开始

注册本机仓库作为 `wttch-ai` marketplace：

```bash
codex plugin marketplace add /Users/wttch/workspace/AI/WttchCodexPlugin
```

安装插件：

```bash
codex plugin add wttch-codex-plugin@wttch-ai
```

检查状态：

```bash
codex plugin list
```

期望状态：

```text
wttch-codex-plugin@wttch-ai  installed, enabled
```

安装后启动新会话，或在 Codex Desktop 中重启应用。首次发现的 Hook 会显示
为 `untrusted`，需要在 Hooks 界面中审查并信任后才会执行。

## 功能概览

### JEV 决策与 Hook

JEV 是独立 runtime，可发现插件内置决策以及当前项目的
`.agents/wttch/jev-decisions/*.yml`。决策定义使用官方的 `questions` 格式，支持：

- `choice`：固定选项选择；
- `noul`：真假判断；
- `score`：按等级评分。

列出决策：

```bash
python3 runtime/jev/main.py list
```

执行决策时，动态输入通过 JSON stdin 传入，避免命令行字符串注入：

```bash
echo '{"state":"需要判断的动态输入"}' |
python3 runtime/jev/main.py run sample-choice
```

Hook 使用独立的 `skills/jev-gate/hook.yml` 配置，不会自动绑定 JEV 决策。
JEV runtime 只执行 YAML 中定义的 `choice`、`noul` 与 `score` 问题，并原样返回结构化结果；
路由、任务创建、Hook 调度和用户介入均由调用方自行实现。

### 模型 Gate

模型 Gate 在每次 `UserPromptSubmit` 时检查当前模型。默认拒绝：

- `gpt-6-luna`
- `gpt-6-sol`
- `gpt-6-astra`

模型名匹配不区分大小写，并将空格、下划线和连字符视为等价分隔符。拒绝时
返回 Codex UserPromptSubmit 支持的 `{"decision":"block","reason":"..."}`。
处理方式由项目 `.agents/wttch/config.yml` 的 `features.model_gate_action` 控制：
`block` 直接阻止，`warn` 添加警告后继续。要关闭模型 Gate，请设置
`features.model_gate: false`。

模型 Gate 只能读取 Hook 事件中的当前模型，不能判断 Codex 界面中的推理强度或
`x1.5 speed`。Hook 事件字段和调试方式见 [Codex Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
如需查看本机实际收到的事件，可临时让 `UserPromptSubmit` Hook 将标准输入中的
JSON 写入本地文件；调试完成后应移除该临时 Hook。

### 功能开关

项目 `.agents/wttch/config.yml` 统一配置 JEV Gate、模型 Gate、OpenRouter 审查、
决策原因和审计日志。插件操作会自动记录到本机 JSONL 日志，
可用 `python3 runtime/settings.py query-log` 查询，并可按操作类型和结果筛选。
运行时诊断同时追加到用户状态目录下的
`runtime.log`；可通过 `WTTCH_PLUGIN_RUNTIME_LOG` 覆盖其路径。

### 插件信息

`plugin-info` Skill 显示工作目录配置字段和已设置的 Wttch 环境变量名称。它不显示任何
配置值，包括 API Key、模型标识和功能开关值。

## 目录结构

```text
.
├── .codex-plugin/plugin.json         # Codex 插件清单
├── .agents/plugins/marketplace.json  # Codex marketplace 入口
├── hooks/hooks.json                  # 生命周期 Hooks
├── runtime/hook_runner.py            # Hook 异常降级为警告
├── runtime/plugin_info.py             # 不含值的本机配置索引
├── runtime/settings.py               # 项目功能设置读取与校验
├── runtime/operation_log.py          # 统一操作日志和查询
├── runtime/wttch_config.py            # Wttch 工作目录配置读取
├── runtime/model_gate.py             # 模型 Gate
├── runtime/jev/                      # 独立 JEV runtime
│   ├── main.py                       # list/run 命令
│   └── __init__.py
├── runtime/jev_gate/                 # Hook 规则实现（兼容模块）
│   ├── main.py                       # JEV Gate 入口
│   ├── policy.py                     # 策略加载和匹配
│   ├── review.py                     # OpenRouter 审查
│   └── gate.py                       # Gate 评估和审计
├── runtime/rag_toolkit/               # 插件代码；RAG 数据保留在调用项目内
├── pyproject.toml                    # Python 依赖与运行时要求
├── uv.lock                           # 锁定的 Python 依赖版本
├── .agents/wttch/config.yml           # 项目 OpenRouter 配置（本地创建）
└── skills/
    ├── README.md                     # Skill 开发约定
    ├── jev-gate/
    ├── rag-toolkit/                   # 项目本地 RAG 记忆库
    │   └── SKILL.md
    │   └── decisions/*.yml            # 内置 JEV 决策
    ├── plugin-settings/
    │   └── SKILL.md                  # 功能开关说明
    └── plugin-info/
        └── SKILL.md                  # 插件辅助功能说明
```

### `PLUGIN_ROOT` 和插件清单

`PLUGIN_ROOT` 表示插件根目录，也就是上面目录结构中的 `.`。它不是固定的
本机路径：本地开发时通常是当前仓库目录；插件安装后则是 Codex 为该插件
分配的安装或缓存目录。Hook 中的 `${PLUGIN_ROOT}` 由 Codex 自动替换，运行时
代码则通过各运行时模块自身的位置计算出同一个目录。

插件只保留 `.codex-plugin/plugin.json`，因为当前 Codex 的本地插件发现流程会
优先使用这份兼容清单。它通过顶层 `hooks` 字段声明 `hooks/hooks.json`，并同时
描述插件名称、版本、技能目录和界面信息。

仓库根目录不放 `plugin.json`。在当前 Codex 版本中，根目录清单可能被按另一种
Agent Plugins 格式解析，导致 `.codex-plugin/plugin.json` 中的 Hook 声明被覆盖，
最终表现为插件技能可以找到，但 Hook 找不到。发布或修改插件元数据时只更新
`.codex-plugin/plugin.json`。

## 环境要求

- Codex Desktop 或支持本地插件的 Codex CLI；
- Python 3.10 或更高版本；
- 使用 OpenRouter `review` 规则时需要 OpenRouter API Key；
- Hook 必须经过用户审查并信任后才会运行。

## Python 运行时维护

插件使用项目虚拟环境运行 Python 依赖。启用前请主动同步环境：

```bash
uv sync
```

`uv.lock` 固定实际安装版本。Hook 通过轻量 `runtime/hook_runner.py` 调用目标脚本；它不做
环境准备，只会将缺依赖、配置错误或运行异常转换为不阻断的 Hook 警告。


## 配置 OpenRouter

将 `wttch-config-example.yml` 的内容写入项目根目录的
`.agents/wttch/config.yml`，再填入 OpenRouter API Key：

```yaml
openrouter:
  api_key: "sk-or-v1-..."
```

`.agents/wttch/config.yml` 应由项目 `.gitignore` 忽略，不应提交。Wttch 插件只从该
项目文件读取 `openrouter.api_key`：Hook 使用事件 `cwd`，普通 Skill 运行时脚本使用其
进程工作目录。其他插件不会自动读取该配置。

模型、API 地址和超时仍通过以下环境变量配置：

| 变量 | 是否必需 | 说明 |
| --- | --- | --- |
| `JEV_OPENROUTER_MODEL` | review 时必需 | OpenRouter 模型 ID，例如 `provider/model-id` |
| `JEV_OPENROUTER_BASE_URL` | 可选 | 默认 `https://openrouter.ai/api/v1` |
| `JEV_OPENROUTER_TIMEOUT` | 可选 | 请求超时秒数，默认 `20` |

示例：

```bash
export JEV_OPENROUTER_MODEL="provider/model-id"
export JEV_OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export JEV_OPENROUTER_TIMEOUT="20"
```

不要把真实密钥写入 `gate.yml`、README、脚本、示例文件或 Git 提交。

## Hook 配置与 JEV runtime

Hook 专用配置位于 `skills/jev-gate/hook.yml`，只负责工具匹配和 Hook 动作。
它与 JEV 决策定义分离。内置决策位于 `skills/jev-gate/decisions/*.yml`，项目级
决策位于项目根目录的 `.agents/wttch/jev-decisions/*.yml`。

对于需要绑定 `UserPromptSubmit` 的 `noul` 决策，可在决策文件顶层添加
`user_prompt_submit`。该字段引用一个正向的 `noul` 问题（例如“是否可安全自动
处理”），并在 YAML 中定义概率阈值和三个分支的 `allow`、`warn` 或 `block` 动作：

`UserPromptSubmit` Hook 只会读取当前项目
`.agents/wttch/jev-decisions/*.yml` 中的此类决策；插件自带的 `sample-*.yml`
仅作为可复制模板，绝不会直接启用。每个项目最多配置一个此类决策。

```yaml
user_prompt_submit:
  question: safe_to_run
  thresholds:
    allow_at_or_above: 0.80
    uncertain_at_or_above: 0.40
  actions:
    allow:
      action: allow
      message: "JEV 判断该请求可自动处理。"
    uncertain:
      action: block
      message: "JEV 判断可信度不足，请明确确认后重新提交。"
    deny:
      action: block
      message: "JEV 判断该请求不适合自动处理。"
```

概率达到 `allow_at_or_above` 时走 `allow`；介于两个阈值之间走 `uncertain`；其余
走 `deny`。若需要用户明确确认，中间分支应使用 `block`，而不是会继续当前请求的
`warn`。

JEV 决策示例：

```yaml
version: 1
model: typesafe/jev-1.13
questions:
  team:
    type: choice
    instructions: "这条消息应该由哪个团队处理？"
    criteria:
      billing: "支付、付款、发票、退款。"
      technical: "缺陷、故障、集成、API 错误。"
      sales: "定价、升级、新账户。"
```

`state` 不写入决策 YAML，而是在执行时通过 JSON stdin 传入。

## 功能开关

功能开关只从调用项目的 `.agents/wttch/config.yml` 读取；没有本机设置文件、插件内
默认值或覆盖优先级。使用 `wttch-config-example.yml` 作为完整模板，并在项目配置中
直接修改：

```yaml
features:
  jev_gate: true
  openrouter_review: true
  show_decision_reason: true
  audit_log: false
  model_gate: true
  model_gate_action: block # block 或 warn
  blocked_models:
    - gpt-6-luna
```

所有已知功能键都必须在 `features` 中出现，运行时会校验类型和未知键。可用
`python3 runtime/settings.py list-settings` 只读检查当前项目配置。若某项配置只适用于
一个功能模块，不要扩展通用 `features`；在该模块的项目目录下新增其专属 YAML，并由该
模块显式读取和校验。

## 验证和测试

检查 YAML 结构和正则表达式：

```bash
python3 runtime/jev_gate/main.py validate-jev-policy \
  --policy skills/jev-gate/hook.yml
```

列出独立 JEV 决策：

```bash
python3 runtime/jev/main.py list
```

模拟一个应被拒绝的 `PreToolUse` 事件：

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /"},"cwd":"/workspace"}' \
  | python3 runtime/jev_gate/main.py jev-gate \
      --policy skills/jev-gate/hook.yml
```

预期结果中的 `permissionDecision` 应为 `deny`。

测试 `review` 规则前，请确认项目 `.agents/wttch/config.yml` 的
`openrouter.api_key` 或 `OPENROUTER_API_KEY` 已设置，并且
`JEV_OPENROUTER_MODEL` 已设置。
运行时不会输出 API Key。

## 更新插件

本地修改会直接从此仓库加载；重新安装以刷新插件：

```bash
codex plugin add wttch-codex-plugin@wttch-ai
```

若本机此前注册过同名的 Git marketplace，先切换到本地路径：

```bash
codex plugin marketplace remove wttch-ai
codex plugin marketplace add /Users/wttch/workspace/AI/WttchCodexPlugin
```

`.codex-plugin/plugin.json` 的版本号仍应在发布版本时递增。

## Hook 发现兼容性

当前发布使用 `.codex-plugin/plugin.json` 声明 `hooks/hooks.json`。Codex Desktop
和 Codex CLI 可以打包不同的 Codex 内核版本，但共享 `~/.codex` 配置。发布后
如果 Hook 首次出现为 `untrusted`，需要在 Hooks 界面中审查并信任后才允许执行。

Hook 首次出现时为 `untrusted`，信任后才允许执行。

## 添加自己的 Skill

在 `skills/` 下为每个工作流创建独立目录：

```text
skills/my-skill/
├── SKILL.md
├── references/     # 可选
├── scripts/        # 可选，Skill 专用脚本
└── assets/         # 可选
```

`SKILL.md` 必须使用与目录一致的小写 kebab-case 名称：

```markdown
---
name: my-skill
description: 说明这个 Skill 做什么，以及应在什么场景使用。
---

# My Skill

在这里编写清晰、可执行的工作流程。
```

如果多个 Skills 需要共享 Python 代码，应扩展根目录的 `runtime/`，并把
第三方依赖加入根目录 `pyproject.toml`，然后运行 `uv lock` 更新 `uv.lock`；不要为每个 Skill 建立重复的
虚拟环境。

## 发布新版本

1. 更新 `.codex-plugin/plugin.json` 的语义化版本号；
2. 验证插件 JSON、Hook JSON 和策略文件；
3. 确认 Skills、Hooks、默认提示和主页信息完整；
4. 重新安装插件并检查状态；
5. 在 Desktop 或 CLI 中使用新会话验证 Hook。

## 安全说明

- 不提交 API Key、Token、Cookie、私钥或 `.env` 文件；
- Hook 在执行工具前获得工具名称和输入，只将命中 `review` 规则的内容发送给
  OpenRouter；
- 静态 `allow` 和 `deny` 规则不会调用远程模型；
- 修改 Gate 策略或 Hook 后，应重新审查其权限和失败行为；
- 对生产环境建议使用 `fail_open: false`，并先在隔离环境测试。

## License

Private use. Copyright Wttch. See <https://wttch.com>.
