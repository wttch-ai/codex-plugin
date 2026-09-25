# Wttch Codex Plugin

Wttch 的私人 Codex 插件，用来集中维护可复用的 Skills、生命周期 Hooks、
策略文件和共享 Python 运行时。

- 主页：<https://wttch.com>
- 插件名称：`wttch-codex-plugin`
- 当前版本：`0.1.10`
- 使用范围：私人插件

## 快速开始

如果尚未配置 `wttch-ai` marketplace：

```bash
codex plugin marketplace add https://github.com/wttch-ai/codex-plugin.git
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

### JEV Gate

`jev-gate` 在 Codex 执行受支持的本地工具前运行 `PreToolUse` Hook，并按照
YAML 策略决定：

- `allow`：直接允许，不调用远程模型；
- `deny`：直接拒绝，不调用远程模型；
- `review`：调用 OpenRouter 中指定的模型进行上下文审查，再返回 `allow`
  或 `deny`。

策略只保存判断规则。模型名称、API 地址、密钥和超时通过环境变量传入，
不会写入仓库。

### 模型 Gate

模型 Gate 在每次 `UserPromptSubmit` 时检查当前模型。默认拒绝：

- `gpt-6-luna`
- `gpt-6-sol`
- `gpt-6-astra`

模型名匹配不区分大小写，并将空格、下划线和连字符视为等价分隔符。拒绝时
返回 Codex UserPromptSubmit 支持的 `{"decision":"block","reason":"..."}`。
处理方式由已注册的 `model_gate_action` 设置控制：`block` 直接阻止并提示如何关闭
模型 Gate，`warn` 添加警告后继续。默认值为 `block`。阻止提示中的关闭命令为：

```bash
python3 runtime/settings.py set-setting model_gate off
```

模型 Gate 只能读取 Hook 事件中的当前模型，不能判断 Codex 界面中的推理强度或
`x1.5 speed`。Hook 事件字段和调试方式见 [Codex Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
如需查看本机实际收到的事件，可临时让 `UserPromptSubmit` Hook 将标准输入中的
JSON 写入本地文件；调试完成后应移除该临时 Hook。

### 功能开关

`plugin-settings` Skill 可以查看和修改本机设置，包括 JEV Gate、模型 Gate、
OpenRouter 审查、决策原因和审计日志。

## 目录结构

```text
.
├── .codex-plugin/plugin.json         # Codex 插件清单
├── .agents/plugins/marketplace.json  # Codex marketplace 入口
├── config/features.json              # 本机功能开关清单
├── hooks/hooks.json                  # 生命周期 Hooks
├── runtime/bootstrap.py              # 环境检查、创建和依赖同步
├── runtime/settings.py               # 本机功能开关
├── runtime/model_gate.py             # 模型 Gate
├── runtime/jev_gate/                 # JEV Gate 独立模块
│   ├── main.py                       # JEV Gate 入口
│   ├── policy.py                     # 策略加载和匹配
│   ├── review.py                     # OpenRouter 审查
│   └── gate.py                       # Gate 评估和审计
├── requirements.txt                  # Python 依赖
└── skills/
    ├── README.md                     # Skill 开发约定
    ├── jev-gate/
    │   ├── SKILL.md                  # JEV Gate 使用说明
    │   └── gate.yml                  # Gate 策略
    └── plugin-settings/
        └── SKILL.md                  # 功能开关说明
```

### `PLUGIN_ROOT` 和插件清单

`PLUGIN_ROOT` 表示插件根目录，也就是上面目录结构中的 `.`。它不是固定的
本机路径：本地开发时通常是当前仓库目录；插件安装后则是 Codex 为该插件
分配的安装或缓存目录。Hook 中的 `${PLUGIN_ROOT}` 由 Codex 自动替换，运行时
代码则通过 `runtime/bootstrap.py` 的位置计算出同一个目录。

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

插件使用一个共享的 Python 虚拟环境。环境位于插件根目录下：

```text
${PLUGIN_ROOT}/.venv/
```

其中：

- macOS/Linux 的解释器是 `${PLUGIN_ROOT}/.venv/bin/python`；
- Windows 的解释器是 `${PLUGIN_ROOT}/.venv/Scripts/python.exe`；
- `${PLUGIN_ROOT}/.venv/requirement.md5` 记录当前环境已经安装过的依赖指纹；
- `${PLUGIN_ROOT}/.venv.bootstrap.lock/` 用于防止多个 Hook 同时初始化环境。

Hook 不会直接运行各个 Gate 脚本，而是先运行 `runtime/bootstrap.py`。Bootstrap
使用系统里的 Python 3 启动，完成环境检查后再切换到 `.venv` 中的 Python，执行
指定的 Skill 脚本。

每次 Hook 都会向 Hook 状态输出环境进度，典型状态包括：

```text
Wttch 环境：正在检查 Python 环境
Wttch 环境：正在创建 Python 虚拟环境
Wttch 环境：正在安装或更新 Python 依赖
Wttch 环境：已就绪，依赖已同步
```

如果环境没有变化，则最后显示：

```text
Wttch 环境：已就绪，复用现有虚拟环境
```

两个 Hook 的界面状态提示也统一为“正在准备 Python 环境”；具体进度由
Bootstrap 的状态输出提供。

### 首次运行

首次触发任意一个 Hook 时，Bootstrap 按以下顺序执行：

1. 读取并校验根目录的 `requirement.md5`；
2. 计算 `requirements.txt` 的 MD5，确认两者一致；
3. 如果 `.venv` 或其中的 Python 解释器不存在，自动执行 `python -m venv .venv`；
4. 执行 `.venv` 中的 `python -m pip install --requirement requirements.txt`；
5. 安装成功后，将本次指纹写入 `.venv/requirement.md5`；
6. 使用 `.venv` 中的 Python 执行对应的 Skill 脚本。

因此，首次 Hook 可能需要额外等待 Python 环境创建和依赖下载完成。

### 插件更新和依赖更新

每次运行时都会比较两个指纹：

```text
插件内的 requirement.md5
        与
.venv/requirement.md5
```

- 指纹相同：直接复用现有环境，不重新安装依赖；
- 指纹不同：重新执行 `pip install -r requirements.txt`，成功后更新虚拟环境中的指纹；
- `.venv` 不存在、解释器丢失或指纹文件丢失：按首次运行流程修复；
- 安装失败：不写入新指纹，下次运行会再次尝试；
- 多个 Hook 同时启动：只有持有锁的进程负责初始化，其他进程等待初始化完成。

更新 `requirements.txt` 后，需要同步重新生成插件根目录的 `requirement.md5`：

```bash
python3 -c "import hashlib, pathlib; print(hashlib.md5(pathlib.Path('requirements.txt').read_bytes()).hexdigest())" > requirement.md5
```

如果 `requirements.txt` 与 `requirement.md5` 不一致，Bootstrap 会直接报错，避免
在插件版本不完整时更新环境。`.venv`、`.venv.bootstrap.lock/` 和虚拟环境中的
`requirement.md5` 都是运行时文件，不应提交到仓库；只有插件根目录的
`requirement.md5` 应随插件版本提交。

## 配置 OpenRouter

运行时读取以下环境变量：

| 变量 | 是否必需 | 说明 |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | review 时必需 | OpenRouter API Key，不要写入仓库 |
| `JEV_OPENROUTER_MODEL` | review 时必需 | OpenRouter 模型 ID，例如 `provider/model-id` |
| `JEV_OPENROUTER_BASE_URL` | 可选 | 默认 `https://openrouter.ai/api/v1` |
| `JEV_OPENROUTER_TIMEOUT` | 可选 | 请求超时秒数，默认 `20` |

示例：

```bash
export OPENROUTER_API_KEY="..."
export JEV_OPENROUTER_MODEL="provider/model-id"
export JEV_OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
export JEV_OPENROUTER_TIMEOUT="20"
```

密钥应保存在本机安全的环境配置或密钥管理工具中。不要把真实密钥写入
`gate.yml`、README、脚本或 Git 提交。

## JEV Gate 策略

策略文件位于 `skills/jev-gate/gate.yml`。示例：

```yaml
version: 1

defaults:
  action: allow
  fail_open: true

rules:
  - id: example-rule
    tools: [Bash, apply_patch]
    input_regex:
      - '(?i)production|deploy'
    action: review
    instruction: >-
      判断此工具调用是否安全且符合用户请求，只返回严格 JSON。
```

规则从上到下匹配，命中第一条后停止。建议按以下顺序排列：

1. 明确且无条件禁止的操作设为 `deny`；
2. 需要理解用户意图和上下文的操作设为 `review`；
3. 确定安全的操作设为 `allow`；
4. 具体规则放在宽泛规则之前。

`defaults.fail_open` 控制 JEV 无法访问时的行为：

- `true`：记录降级原因并允许工具调用；
- `false`：拒绝工具调用，直到 JEV 恢复可用。

## 功能开关

`plugin-settings` Skill 通过共享 runtime 管理本机设置：

```bash
python3 runtime/settings.py list-settings
python3 runtime/settings.py set-setting jev_gate off
python3 runtime/settings.py set-setting audit_log on
python3 runtime/settings.py set-setting model_gate on
python3 runtime/settings.py set-setting blocked_models 'gpt-6-luna,gpt-6-sol,gpt-6-astra'
python3 runtime/settings.py set-setting model_gate_action warn
python3 runtime/settings.py reset-settings
```

`model_gate_action` 支持 `block` 和 `warn`。

插件设置以注册表形式统一维护在 `config/features.json`。每个注册项包含
`key`、显示名称、说明、类型、默认值，以及可选的 `choices`。`settings.py`
会自动校验注册项，并让 `list-settings` 和 `plugin-settings` Skill 发现和显示
所有已注册设置。用户覆盖值保存在：

```text
~/.config/wttch-codex-plugin/settings.json
```

新增开关时，应同时登记 `key`、名称、说明和默认值，并在对应 runtime 中
读取它；不要创建没有调用方的空开关。

## 验证和测试

检查 YAML 结构和正则表达式：

```bash
python3 runtime/bootstrap.py runtime/jev_gate/main.py validate-jev-policy \
  --policy skills/jev-gate/gate.yml
```

模拟一个应被拒绝的 `PreToolUse` 事件：

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /"},"cwd":"/workspace"}' \
  | python3 runtime/bootstrap.py runtime/jev_gate/main.py jev-gate \
      --policy skills/jev-gate/gate.yml
```

预期结果中的 `permissionDecision` 应为 `deny`。

测试 `review` 规则前，请确认 `OPENROUTER_API_KEY` 和
`JEV_OPENROUTER_MODEL` 已设置。运行时不会输出 API Key。

## 更新插件

发布新版本后重新安装：

```bash
codex plugin add wttch-codex-plugin@wttch-ai
```

Codex 会按清单版本使用对应缓存。发布修复时应更新
`.codex-plugin/plugin.json` 中的语义化版本号，避免继续使用旧缓存。

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
第三方依赖加入根目录 `requirements.txt`；不要为每个 Skill 建立重复的
虚拟环境。

## 发布新版本

1. 更新 `.codex-plugin/plugin.json` 的语义化版本号；
2. 验证插件 JSON、Hook JSON 和策略文件；
3. 确认 Skills、Hooks、默认提示和主页信息完整；
4. 提交并推送 marketplace 指向的仓库；
5. 重新安装插件并检查状态；
6. 在 Desktop 或 CLI 中使用新会话验证 Hook。

## 安全说明

- 不提交 API Key、Token、Cookie、私钥或 `.env` 文件；
- Hook 在执行工具前获得工具名称和输入，只将命中 `review` 规则的内容发送给
  OpenRouter；
- 静态 `allow` 和 `deny` 规则不会调用远程模型；
- 修改 Gate 策略或 Hook 后，应重新审查其权限和失败行为；
- 对生产环境建议使用 `fail_open: false`，并先在隔离环境测试。

## License

Private use. Copyright Wttch. See <https://wttch.com>.
