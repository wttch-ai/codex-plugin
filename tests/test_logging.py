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

from operation_log import query, record, record_runtime  # noqa: E402
from runner import main as runner_main  # noqa: E402
from wttch_logging import LOGGER_NAME, log_path  # noqa: E402


class UnifiedLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_daily_log_filename(self) -> None:
        moment = datetime(2026, 10, 16, 12, 30)
        with patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": ""}):
            path = log_path(moment)
        self.assertEqual(path, Path.home() / ".wttch" / "logs" / "2026-10-16.log")

    def test_logs_only_to_daily_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.dict(os.environ, {"WTTCH_PLUGIN_LOG_DIR": directory}),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                record("test.operation", details={"decision": "allow"})
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
                operations = query(operation="test.operation")
            self.assertEqual(operations[0]["details"], {"decision": "allow"})

            # Windows cannot remove an open FileHandler target.
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    def test_runner_status_reports_runtime_and_logging_without_writing_logs(self) -> None:
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
