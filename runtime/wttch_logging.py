"""Wttch 插件统一的仅文件日志实现。

Hook 的 stdout 是 Codex 协议通道，任何普通日志进入 stdout 或 stderr 都可能破坏
Hook JSON。因此本模块只创建文件 Handler、关闭向 Python 根 Logger 的传播，并在
文件不可写时静默降级到 ``NullHandler``。日志按本地日期写入
``~/.wttch/logs/YYYY-MM-DD.log``；JEV 判决独立写入
``~/.wttch/logs/jev-YYYY-MM-DD.log``。单行格式尽量与 Spring Boot 默认文件日志一致，
方便熟悉 Java 服务日志的维护者直接阅读和检索。

本模块同时负责运行诊断、结构化操作信息的文本化以及只读查询。调用方只能传入经过
筛选的安全元数据。除 JEV 判决请求和响应（为支持判决审计而明确记录）外，调用方禁止
把完整 Hook 输入、用户提示词、API Key 或工具参数写入日志。
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import re
from threading import RLock
from typing import Any

from paths import DEFAULT_LOG_ROOT


LOGGER_NAME = "wttch"
JEV_LOGGER_NAME = f"{LOGGER_NAME}.jev"
_MANAGED_HANDLER = "_wttch_file_handler"
_LOCK = RLock()

# Spring Boot 默认格式（logging.pattern.file）的行结构。查询接口只接受能被此表达式
# 完整识别的首行，以免把异常堆栈续行误当成独立日志事件。
LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<level>[A-Z]+)\s+\d+\s+---\s+\[\s*(?P<thread>[^\]]*?)\s*\]\s+"
    r"(?P<logger>\S+)\s+:\s(?P<message>.*)$"
)


def log_root() -> Path:
    """返回统一日志目录。

    正常运行固定使用 ``~/.wttch/logs``；环境变量只用于测试隔离，避免测试创建或读取
    用户的真实日志文件。
    """
    override = os.environ.get("WTTCH_PLUGIN_LOG_DIR", "").strip()
    return Path(override).expanduser() if override else DEFAULT_LOG_ROOT


def log_path(moment: datetime | None = None) -> Path:
    """按本地日历日期计算日志文件，而不是按 UTC 日期切分。

    ``moment`` 主要供测试注入确定时间；省略时显式使用带本地时区的当前时间，确保午夜
    后重新配置 Handler 时切换到新文件。
    """
    current = moment or datetime.now().astimezone()
    return log_root() / f"{current:%Y-%m-%d}.log"


def jev_log_path(moment: datetime | None = None) -> Path:
    """按本地日历日期返回独立的 JEV 判决日志文件路径。"""
    current = moment or datetime.now().astimezone()
    return log_root() / f"jev-{current:%Y-%m-%d}.log"


def render_field(value: Any) -> str:
    """把操作字段编码为可读且不跨行的 ``key=value`` 值。

    简单值保持原样，含空白或双引号的值使用双引号包裹，并转义反斜杠与双引号。
    调用方仍须保证值不含敏感信息；该函数只解决显示歧义，不承担脱敏职责。
    """
    text = str(value)
    if text and not any(character.isspace() for character in text) and '"' not in text:
        return text
    # 先转义反斜杠，再把控制换行变成可见序列，确保一个字段不会拆开日志首行。
    escaped = (
        text.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )
    return f'"{escaped}"'


class SpringBootFormatter(logging.Formatter):
    """按 Spring Boot 默认文件日志布局渲染 Python ``LogRecord``。

    对齐和截断规则模拟 ``%d{yyyy-MM-dd HH:mm:ss.SSS} %5p %pid --- [%15.15t]
    %-40.40logger{39} : %m``。Python 与 Java 的线程、Logger 实现不同，因此只承诺
    可读布局和查询正则兼容，不宣称字节级完全一致。
    """

    def format(self, record: logging.LogRecord) -> str:
        """输出日志首行；存在异常时在首行后附加标准堆栈文本。"""
        moment = datetime.fromtimestamp(record.created)
        timestamp = f"{moment:%Y-%m-%d %H:%M:%S}.{moment.microsecond // 1000:03d}"
        # 对应 pattern 中 %5p、%15.15t 与 %-40.40logger{39} 的对齐和截断规则。
        line = (
            f"{timestamp} {record.levelname:>5} {os.getpid()} --- "
            f"[{record.threadName[:15]:>15}] {record.name[:39]:<40} : {record.getMessage()}"
        )
        # 堆栈保持 logging 的标准多行格式。query_log 只返回首行，不把续行拆成事件。
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


class SilentFileHandler(logging.FileHandler):
    """A FileHandler whose write failures never fall back to stderr."""

    def handleError(self, record: logging.LogRecord) -> None:
        """吞掉文件写入错误，禁止 logging 默认错误报告污染 Hook stderr。

        日志是旁路诊断能力，磁盘满、权限不足或文件被占用都不能改变 Gate 的允许、警告
        或阻止结果。
        """
        return


def _configure_file_logger(logger_name: str, desired_path: Path) -> logging.Logger:
    """幂等配置指定的仅文件 Logger，并在日期或测试目录变化时轮换文件。

    ``_LOCK`` 防止同一进程中的并发 Hook 同时创建多个 Handler。函数会清理非本模块
    管理的 Handler，保证 Wttch Logger 不会继承 ConsoleHandler；创建文件失败时安装
    ``NullHandler``，同时抑制 ``logging.lastResort`` 向 stderr 输出。
    """
    logger = logging.getLogger(logger_name)
    desired_path = desired_path.resolve()
    with _LOCK:
        for handler in list(logger.handlers):
            if getattr(handler, _MANAGED_HANDLER, False):
                current_path = Path(handler.baseFilename).resolve()
                if current_path == desired_path:
                    logger.setLevel(logging.INFO)
                    logger.propagate = False
                    return logger
            # 日期变化、测试目录变化或外部 Handler 注入时统一替换，避免重复写入。
            logger.removeHandler(handler)
            handler.close()

        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            desired_path.parent.mkdir(parents=True, exist_ok=True)
            handler = SilentFileHandler(desired_path, encoding="utf-8")
            setattr(handler, _MANAGED_HANDLER, True)
            handler.setFormatter(SpringBootFormatter())
            logger.addHandler(handler)
        except (OSError, TypeError, ValueError):
            # NullHandler also suppresses logging.lastResort, which writes to stderr.
            logger.addHandler(logging.NullHandler())
        return logger


def _configure_root_logger() -> logging.Logger:
    """配置普通插件操作和运行诊断的按日文件 Logger。"""
    return _configure_file_logger(LOGGER_NAME, log_path())


def _configure_jev_logger() -> logging.Logger:
    """配置 JEV 判决专用的按日文件 Logger。"""
    return _configure_file_logger(JEV_LOGGER_NAME, jev_log_path())


def get_logger(component: str) -> logging.Logger:
    """返回只向受管文件 Logger 传播的组件 Logger。

    每次调用都会移除组件 Logger 上可能由外部代码附加的 Handler，从而确保
    ``wttch.operation``、``wttch.runtime`` 等子 Logger 不会绕过仅文件策略。
    """
    _configure_root_logger()
    logger = logging.getLogger(f"{LOGGER_NAME}.{component}")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    return logger


def get_jev_logger() -> logging.Logger:
    """返回不会传播到普通插件日志的 JEV 判决专用 Logger。"""
    return _configure_jev_logger()


def record_runtime(message: str) -> None:
    """记录一条运行时警告，任何日志异常都不得影响调用方。

    该入口用于环境创建、依赖安装和目标脚本执行失败。消息应是维护者可读的摘要，不能
    包含完整 Hook 输入或凭据。
    """
    try:
        get_logger("runtime").warning(message)
    except (OSError, TypeError, ValueError, KeyError):
        return


def record_operation(
    operation: str,
    *,
    result: str = "ok",
    details: dict[str, Any] | None = None,
) -> None:
    """追加一条可检索的操作记录，且不影响插件主流程。

    输出消息形如 ``model_gate result=ok decision=allow``。``None`` 字段会被省略，避免
    产生没有信息量的值；字段经过 ``render_field`` 处理后仍保持单行，便于关键词检索。
    """
    fields = [f"result={render_field(result)}"]
    for key, value in (details or {}).items():
        if value is not None:
            fields.append(f"{key}={render_field(value)}")
    try:
        get_logger("operation").info(f"{operation} {' '.join(fields)}")
    except (OSError, TypeError, ValueError, KeyError):
        return


def record_jev_operation(
    operation: str,
    *,
    result: str = "ok",
    details: dict[str, Any] | None = None,
) -> None:
    """把 JEV 判决审计事件写入 ``jev-YYYY-MM-DD.log``。"""
    fields = [f"result={render_field(result)}"]
    for key, value in (details or {}).items():
        if value is not None:
            fields.append(f"{key}={render_field(value)}")
    try:
        get_jev_logger().info(f"{operation} {' '.join(fields)}")
    except (OSError, TypeError, ValueError, KeyError):
        return


def query_log(
    *,
    keyword: str | None = None,
    level: str | None = None,
    limit: int = 100,
) -> list[str]:
    """跨日期返回最近匹配的日志首行原文。

    ``level`` 不区分输入大小写，``keyword`` 对整行做区分大小写的字面包含匹配。
    文件按名称升序读取（包括 ``jev-YYYY-MM-DD.log``），最终截取最后 ``limit`` 条，因此结果仍按
    时间先后排列。格式不合法的行和异常堆栈续行会被忽略；该查询不会创建新日志。
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    wanted_level = level.upper() if level else None
    matches: list[str] = []
    # 跨日按文件名顺序读取，最后统一截取最近的 limit 条匹配行。
    for path in sorted(log_root().glob("*.log")):
        with path.open("r", encoding="utf-8") as stream:
            for raw in stream:
                line = raw.rstrip("\r\n")
                entry = LOG_LINE_PATTERN.match(line)
                # 只查询规范首行；用户手工写入的文本和异常堆栈续行不参与筛选。
                if entry is None:
                    continue
                if wanted_level and entry.group("level") != wanted_level:
                    continue
                if keyword and keyword not in line:
                    continue
                matches.append(line)
    # 文件名前缀不同，不能依赖目录遍历顺序代表时间顺序。
    return sorted(matches, key=lambda line: line[:23])[-limit:]
