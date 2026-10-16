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
    log_path,
    query_operations,
    record_operation,
    record_runtime,
)


class UnifiedLoggingTests(unittest.TestCase):
    """覆盖日志路径、JSONL 事件、查询接口和 runner 状态。"""

    def tearDown(self) -> None:
        """关闭文件 Handler，避免 Windows 锁住临时日志目录。"""
        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_daily_log_filename(self) -> None:
        """日志文件名必须按本地日期切分。"""
        moment = datetime(2026, 10, 16, 12, 30)
        with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": ""}):
            path = log_path(moment)
        self.assertEqual(path, Path.home() / ".wttch" / "logs" / "2026-10-16.log")

    def test_logs_only_to_daily_file(self) -> None:
        """运行时和操作事件只能进入 JSONL 文件，不能进入控制台。"""
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
            entries = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["logger"] for entry in entries], [
                "wttch.operation",
                "wttch.runtime",
            ])

            with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}):
                operations = query_operations(operation="test.operation")
            self.assertEqual(operations[0]["details"], {"decision": "allow"})

            # Windows cannot remove an open FileHandler target.
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_runner_status_reports_runtime_and_logging_without_writing_logs(self) -> None:
        """status 只报告安全元数据，且查询本身不能创建日志。"""
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
            self.assertFalse(status["logging"]["console_output"])
            self.assertEqual(list(Path(directory).glob("*.log")), [])


if __name__ == "__main__":
    unittest.main()
