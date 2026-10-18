"""验证统一日志只写每日文件，并且不污染 Hook 标准输出。"""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from runner import main as runner_main  # noqa: E402
from wttch_logging import (  # noqa: E402
    LOGGER_NAME,
    JEV_LOGGER_NAME,
    LOG_LINE_PATTERN,
    jev_log_path,
    log_path,
    query_log,
    record_jev_operation,
    record_operation,
    record_runtime,
    render_field,
)


class UnifiedLoggingTests(unittest.TestCase):
    """覆盖日志路径、Spring Boot 文本布局、静默保证、查询接口和 runner 状态。

    测试始终通过 ``WTTCH_PLUGIN_LOG_DIR`` 使用临时目录，既验证生产代码的目录覆盖
    能力，也确保不会读取或污染开发者 ``~/.wttch/logs`` 中的真实日志。
    """

    def tearDown(self) -> None:
        """关闭文件 Handler，避免 Windows 锁住临时日志目录。"""
        for logger_name in (LOGGER_NAME, JEV_LOGGER_NAME):
            logger = logging.getLogger(logger_name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_daily_log_filename(self) -> None:
        """日志文件名必须按本地日期切分。"""
        moment = datetime(2026, 10, 16, 12, 30)
        with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": ""}):
            path = log_path(moment)
        self.assertEqual(path, Path.home() / ".wttch" / "logs" / "2026-10-16.log")

    def test_jev_daily_log_filename(self) -> None:
        """判决审计日志必须使用独立的 jev- 日期文件名。"""
        moment = datetime(2026, 10, 16, 12, 30)
        with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": ""}):
            path = jev_log_path(moment)
        self.assertEqual(path, Path.home() / ".wttch" / "logs" / "jev-2026-10-16.log")

    def test_operation_fields_remain_on_one_log_line(self) -> None:
        """含空白、引号或换行的字段必须转义，不能破坏日志首行边界。"""
        self.assertEqual(render_field("allow"), "allow")
        self.assertEqual(render_field('needs "review"'), '"needs \\"review\\""')
        self.assertEqual(render_field("first\nsecond"), '"first\\nsecond"')

    def test_jev_operations_use_the_dedicated_daily_file(self) -> None:
        """JEV 审计事件不能混入普通插件操作日志。"""
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}):
                record_jev_operation("jev_decision_input", details={"input": "state"})

                files = list(Path(directory).glob("*.log"))
                self.assertEqual([path.name for path in files], [jev_log_path().name])
                line = files[0].read_text(encoding="utf-8").strip()
                self.assertIn("jev_decision_input result=ok input=state", line)
                self.assertEqual(query_log(keyword="jev_decision_input"), [line])

    def test_logs_only_to_daily_file(self) -> None:
        """两类事件必须共用文本日志，同时严格保持 stdout/stderr 为空。

        除了检查布局正则，还验证组件 Logger、字段渲染、关键词筛选和大小写无关的级别
        筛选，防止格式变更导致查询接口与实际文件脱节。
        """
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                record_operation("test.operation", details={"decision": "allow"})
                record_runtime("runtime diagnostic")

            logger = logging.getLogger(LOGGER_NAME)
            for handler in logger.handlers:
                handler.flush()
                self.assertIsNot(getattr(handler, "stream", None), sys.stdout)
                self.assertIsNot(getattr(handler, "stream", None), sys.stderr)

            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            files = list(Path(directory).glob("*.log"))
            self.assertEqual(len(files), 1)
            lines = files[0].read_text(encoding="utf-8").splitlines()
            # 使用生产查询相同的正则解析，确保写入格式和读取格式共同演进。
            entries = [LOG_LINE_PATTERN.match(line) for line in lines]
            self.assertTrue(all(entries), lines)
            self.assertEqual(
                [(entry.group("level"), entry.group("logger")) for entry in entries],
                [("INFO", "wttch.operation"), ("WARNING", "wttch.runtime")],
            )
            self.assertEqual(
                entries[0].group("message"),
                "test.operation result=ok decision=allow",
            )
            self.assertEqual(entries[1].group("message"), "runtime diagnostic")

            with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}):
                self.assertEqual(query_log(keyword="test.operation"), [lines[0]])
                self.assertEqual(query_log(level="warning"), [lines[1]])
                self.assertEqual(query_log(keyword="absent.operation"), [])

            # Windows cannot remove an open FileHandler target.
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_runner_status_reports_runtime_and_logging_without_writing_logs(self) -> None:
        """status 只报告安全元数据，且观察日志状态本身不能创建日志文件。"""
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                result = runner_main(["--mode", "status"])
            self.assertEqual(result, 0)
            self.assertEqual(stderr.getvalue(), "")
            status = json.loads(stdout.getvalue())
            self.assertIn("virtual_environment", status["runtime"])
            self.assertIn("ready", status["runtime"])
            self.assertEqual(status["logging"]["directory"], directory)
            self.assertEqual(
                status["logging"]["jev_current_file"],
                str(Path(directory) / jev_log_path().name),
            )
            # status 的格式标识是 plugin-utils 展示给用户的稳定契约。
            self.assertEqual(status["logging"]["format"], "spring-boot")
            self.assertFalse(status["logging"]["console_output"])
            self.assertEqual(list(Path(directory).glob("*.log")), [])


if __name__ == "__main__":
    unittest.main()
