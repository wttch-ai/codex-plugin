---
name: plugin-utils
description: 查看 Wttch 插件配置、运行时与日志状态，并在用户明确请求时创建默认配置或维护插件 Python 环境；不显示配置值或密钥。
---

# Plugin Utilities

## 查看插件配置

显示当前工作目录中 Wttch 插件的配置索引。运行共享 runtime：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode run "${PLUGIN_ROOT}/runtime/plugin_utils.py"
```

输出中的字段含义如下：

- `working_directory_config_fields`：项目 `.agents/wttch/config.yml` 中已存在的字段路径；

只报告配置名称和来源。不要读取、推断、回显或要求用户提供任何配置值，包括
API Key、模型标识、地址、超时和功能开关值。

## 查看运行时与日志状态

该状态入口只依赖本地 Python，即使插件虚拟环境尚未创建也可以运行：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode status
```

在 Windows PowerShell 中运行：

```powershell
python "$env:PLUGIN_ROOT/runtime/runner.py" --mode status
```

只报告以下安全元数据，不读取或输出日志内容：

- `runtime.virtual_environment`、`runtime.python` 与 `runtime.ready`；
- `runtime.requirements`；
- `logging.directory`、`logging.current_file` 与文件是否存在；
- 日志格式以及 `console_output: false` 安全状态。

插件日志固定保存到 `~/.wttch/logs/YYYY-MM-DD.log`，每行一个 JSON 对象，并且不会
写入 Hook 的 stdout 或 stderr。需要查询结构化操作记录时，通过共享环境运行：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode run \
  "${PLUGIN_ROOT}/runtime/settings.py" query-log \
  [--operation <name>] [--result <result>] [--limit <count>]
```

查询会读取日志文件并将筛选结果显式输出；不要在 Hook 执行期间主动查询或展示日志。

## 配置示例

`example/config.yml` 是插件支持的完整配置示例，不是当前项目配置，也不会被 Hook 或
runtime 自动读取。查看示例时应明确告知用户它只包含演示值和占位符，不能把其中的
API Key 当作有效凭据。

## 创建默认项目配置

仅当用户明确要求创建、生成或初始化 Wttch 默认配置时执行。将
`${PLUGIN_ROOT}/skills/plugin-utils/example/config.yml` 复制到当前项目的
`.agents/wttch/config.yml`，并创建缺失的父目录。

目标文件已存在时不要覆盖；报告它已存在，并让用户决定是否自行替换或修改。复制后只报告
文件路径，并提醒用户将示例 API Key 替换为自己的值；不要读取、显示或要求用户提供该值。

## 准备 Python 环境

仅当用户明确要求准备环境、安装依赖、修复缺包或重装依赖时执行。不要在 Hook 运行期间
自动同步或安装。

插件根目录由 Codex 注入的 `PLUGIN_ROOT` 环境变量确定，不依赖当前工作目录。插件共享
环境固定在 `~/.wttch/agent-runtime/venv`，不会写入版本化的插件安装或缓存目录。

首次准备、常规同步或依赖声明变更后，运行；该入口使用本地 Python 创建共享虚拟环境，
再使用虚拟环境自己的 `python -m pip` 安装 `requirements.txt`，不修改全局 Python 包：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode prepare
```

用户要求强制重装全部依赖时，运行：

```bash
python "${PLUGIN_ROOT}/runtime/runner.py" --mode reinstall
```

在 Windows PowerShell 中同样使用本地 Python：

```powershell
python "$env:PLUGIN_ROOT/runtime/runner.py" --mode prepare
python "$env:PLUGIN_ROOT/runtime/runner.py" --mode reinstall
```

同步成功后，插件环境位于 `~/.wttch/agent-runtime/venv`。若本地 Python 不支持 `venv`
或安装失败，报告具体错误和下一步建议；不要改用全局 `pip` 安装依赖。
