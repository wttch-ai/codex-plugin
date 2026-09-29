"""插件运行时使用的静态路径常量。

所有运行时模块都应从这里引用路径，避免分别计算插件根目录或重复拼接配置路径。
插件安装后 ``PLUGIN_ROOT`` 会随 Codex 的安装目录变化；用户状态目录则固定在当前
用户的 Home 目录下，并可由各模块支持的环境变量覆盖。
"""

from pathlib import Path


# 插件根目录：由当前文件的位置反推出，不依赖启动命令的工作目录。
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# 共享 Python 运行时脚本所在目录，Bootstrap 只允许执行此目录内的模块。
RUNTIME_ROOT = PLUGIN_ROOT / "runtime"
# Python 依赖清单。
REQUIREMENTS_PATH = PLUGIN_ROOT / "requirements.txt"
# 插件共享虚拟环境、已安装依赖指纹和跨 Hook 初始化锁。
# 这些是运行时生成内容，不应提交到仓库。
VENV_PATH = PLUGIN_ROOT / ".venv"
VENV_DIGEST_PATH = VENV_PATH / "requirement.md5"
BOOTSTRAP_LOCK_PATH = PLUGIN_ROOT / ".venv.bootstrap.lock"
# 兼容已有 JEV Gate 审计日志的默认位置；是否写入由 audit_log 开关控制。
DEFAULT_AUDIT_LOG_PATH = Path.home() / ".local" / "state" / "wttch-codex-plugin" / "audit.jsonl"
# 所有插件操作的统一 JSONL 日志位置；记录安全元数据，不记录敏感输入。
DEFAULT_OPERATION_LOG_PATH = Path.home() / ".local" / "state" / "wttch-codex-plugin" / "operations.jsonl"
# Human-readable diagnostic log, including bootstrap failures.
DEFAULT_RUNTIME_LOG_PATH = Path.home() / ".local" / "state" / "wttch-codex-plugin" / "runtime.log"
