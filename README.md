# Wttch Codex Plugin

Wttch 的私人 Codex 插件集合，用来集中维护可复用的 skills、生命周期
hooks、策略文件和共享 Python 运行时。

- 主页：<https://wttch.com>
- 插件名称：`wttch-codex-plugin`
- 当前版本：`0.1.2`
- 使用范围：私人插件

## 功能概览

当前包含 `jev-gate` skill。它在 Codex 执行受支持的本地工具前运行
`PreToolUse` hook，并按照 YAML 策略决定：

- `allow`：直接允许，不调用远程模型；
- `deny`：直接拒绝，不调用远程模型；
- `review`：调用 OpenRouter 中指定的模型，由 JEV 对当前工具调用进行
  上下文审查并返回 `allow` 或 `deny`。

YAML 只保存 gate 策略。模型名称、API 地址、密钥和超时均由环境变量
传入，避免把运行时设置或敏感信息混入策略文件。

## 目录结构

```text
.
├── plugin.json                       # Agent Plugins 1.0 主清单
├── .codex-plugin/plugin.json         # 旧版 Codex 兼容清单
├── .agents/plugins/marketplace.json  # 本地 marketplace 入口
├── .codex/config.toml                # 当前项目的插件启用配置
├── hooks/hooks.json                  # Codex 生命周期 hook
├── runtime/run.py                    # 所有 Python skill 共用的运行时入口
├── requirements.txt                  # 统一 Python 依赖
└── skills/
    ├── README.md                     # 新增 skill 的目录约定
    └── jev-gate/
        ├── SKILL.md                  # JEV gate 使用说明
        └── gate.yml                  # 仅包含 gate 策略
```

## 环境要求

- ChatGPT/Codex 桌面端或支持本地插件的 Codex CLI；
- Python 3.10 或更高版本；
- 使用 JEV `review` 规则时，需要 OpenRouter API key；
- 本地 hook 必须由用户审查并信任后才会运行。

## 安装 Python 运行时

整个插件只使用一个 Python 环境和一份 `requirements.txt`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

当前 hook 命令使用 `python3`。可以在启动 Codex 前激活虚拟环境：

```bash
source .venv/bin/activate
```

也可以在创建虚拟环境后，将 `hooks/hooks.json` 中的解释器改成：

```text
${PLUGIN_ROOT}/.venv/bin/python
```

## 配置 OpenRouter

运行时读取以下环境变量：

| 变量 | 是否必需 | 说明 |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | review 时必需 | OpenRouter API 密钥，不要写入仓库 |
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

密钥只应放在本机安全的环境配置中。不要把真实密钥写进 `gate.yml`、
README、shell 脚本或 Git 提交。

## JEV gate 策略

策略文件位于 `skills/jev-gate/gate.yml`。顶层结构如下：

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

规则按从上到下的顺序匹配，命中第一条后停止：

1. 把明确、无条件禁止的操作设为 `deny`；
2. 把需要理解用户意图和上下文的操作设为 `review`；
3. 把确定安全的操作设为 `allow`；
4. 具体规则放在宽泛规则之前。

`defaults.fail_open` 控制 JEV 无法访问时的行为：

- `true`：记录降级原因并允许工具调用；
- `false`：拒绝工具调用，直到 JEV 恢复可用。

## 验证和测试

检查 YAML 结构和正则表达式：

```bash
python3 runtime/run.py validate-jev-policy \
  --policy skills/jev-gate/gate.yml
```

模拟一个应被拒绝的 `PreToolUse` 事件：

```bash
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"rm -rf /"},"cwd":"/workspace"}' \
  | python3 runtime/run.py jev-gate \
      --policy skills/jev-gate/gate.yml
```

预期结果中的 `permissionDecision` 应为 `deny`。

测试 `review` 规则前，请确认 `OPENROUTER_API_KEY` 和
`JEV_OPENROUTER_MODEL` 已设置。运行时不会输出 API key。

## 添加自己的 skill

在 `skills/` 下为每个工作流创建独立目录：

```text
skills/my-skill/
├── SKILL.md
├── references/     # 可选
├── scripts/        # 可选，skill 专用脚本
└── assets/         # 可选
```

`SKILL.md` 必须使用与目录一致的小写 kebab-case 名称：

```markdown
---
name: my-skill
description: 说明这个 skill 做什么，以及应在什么场景使用。
---

# My skill

在这里编写清晰、可执行的工作流程。
```

如果多个 skills 需要共享 Python 代码，应扩展根目录的 `runtime/`，并把
第三方依赖加入根目录 `requirements.txt`；不要给每个 skill 建立重复的
虚拟环境。

## 本地加载

仓库已包含本地 marketplace 配置。首次使用时执行：

```bash
codex plugin marketplace add /absolute/path/to/WttchCodexPlugin
codex plugin add wttch-codex-plugin@wttch-local
```

检查状态：

```bash
codex plugin marketplace list
codex plugin list
```

期望状态为：

```text
wttch-codex-plugin@wttch-local  installed, enabled
```

修改插件后重新执行 `codex plugin add` 刷新本地缓存，并重启桌面端。
已打开的会话不会热加载新增或修改后的 skill。

## 版本与发布

发布新版本时：

1. 更新根目录 `plugin.json` 的语义化版本号；
2. 同步 `.codex-plugin/plugin.json` 中的版本和重复元数据；
3. 验证两个 JSON 清单及所有策略文件；
4. 确认 skills、hooks、默认提示和主页信息没有意外丢失；
5. 打包单个 `wttch-codex-plugin/` 目录后更新私人插件；
6. 回读发布结果，并刷新本机 marketplace 安装缓存。

## 安全说明

- 不提交 API key、token、cookie、私钥或 `.env` 文件；
- hook 在执行工具前获得工具名称与输入，只发送命中 `review` 规则的内容
  给 OpenRouter；
- 静态 `allow` 和 `deny` 规则不会调用远程模型；
- 修改 gate 策略或 hook 后，应重新审查其权限与失败行为；
- 对生产环境建议使用 `fail_open: false`，并先在隔离环境测试。

## License

Private use. Copyright Wttch. See <https://wttch.com>.
