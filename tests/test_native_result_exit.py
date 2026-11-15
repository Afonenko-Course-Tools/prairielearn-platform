"""Native worker читает корректный результат только при успешной доставке JSON."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_plain_runtime import grader
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from json_boundary import JSONObject, json_object


class NativeResultExit(unittest.TestCase):
    def invoke(self, verification: bool = False) -> tuple[int, JSONObject]:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            (job / "tests").mkdir()
            (job / "tests/grading-job.json").write_text("{}")
            argv = ["grade.py", "--job-dir", str(job)]
            if verification:
                argv.append("--verification")
            with (
                patch("sys.argv", argv),
                patch.object(
                    grader,
                    "grade",
                    side_effect=grader.GraderError("PRIVATE_TOOL_CANARY"),
                ),
            ):
                status = grader.main()
            return status, json_object(
                json.loads((job / "results/results.json").read_text())
            )

    def test_native_worker_receives_safe_ungradable_result(self) -> None:
        status, result = self.invoke()
        self.assertEqual(status, 0)
        self.assertFalse(result["gradable"])
        self.assertTrue(result["grading_error"])
        self.assertEqual(result["classification"], "infrastructure-failure")
        self.assertNotIn("score", result)
        message = result["message"]
        assert isinstance(message, str)
        self.assertIn("Проверка недоступна", message)
        self.assertNotIn("PRIVATE_TOOL_CANARY", json.dumps(result))

    def test_operator_verification_keeps_failure_exit_and_private_diagnostic(
        self,
    ) -> None:
        status, result = self.invoke(verification=True)
        self.assertEqual(status, 2)
        self.assertFalse(result["gradable"])
        self.assertNotIn("score", result)
        self.assertEqual(result["message"], "PRIVATE_TOOL_CANARY")
