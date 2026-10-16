"""插件运行时使用的静态路径常量。

所有运行时模块都应从这里引用路径，避免分别计算插件根目录或重复拼接配置路径。
插件安装后 ``PLUGIN_ROOT`` 会随 Codex 的安装目录变化；用户状态目录则固定在当前
用户的 Home 目录下，并可由各模块支持的环境变量覆盖。
"""

from pathlib import Path


# 插件根目录：由当前文件的位置反推出，不依赖启动命令的工作目录。
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# 插件依赖环境独立于 Codex 的版本化插件缓存，升级或重装插件时可以复用。
RUNTIME_ROOT = Path.home() / ".wttch" / "agent-runtime"
RUNTIME_VENV = RUNTIME_ROOT / "venv"
# 所有插件组件共用按本地日期分割的文件日志目录。
DEFAULT_LOG_ROOT = Path.home() / ".wttch" / "logs"
