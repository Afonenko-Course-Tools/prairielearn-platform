"""Некорректный JSON descriptor не мешает доставить безопасный native RESULTS."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gradle_unit_fixtures import unit_platform
from platform_modules import load_java_grader, load_student_feedback
from json_boundary import json_object


CANARY = "PRIVATE_MALFORMED_DESCRIPTOR_CANARY"


class NativeMalformedDescriptor(unittest.TestCase):
    def test_native_cli_delivers_ungradable_json_for_non_object_descriptor(
        self,
    ) -> None:
        grader = load_java_grader(unit_platform(self) / "images/java25-grader/grade.py")
        malformed: list[object] = [None, [], CANARY, [CANARY]]
        for descriptor in malformed:
            with (
                self.subTest(descriptor=descriptor),
                tempfile.TemporaryDirectory() as temporary,
            ):
                job = Path(temporary)
                (job / "tests").mkdir()
                (job / "tests/grading-job.json").write_text(json.dumps(descriptor))
                # Настоящий grade отвергает descriptor до preflight/JVM; main обязан доставить RESULTS.
                with patch("sys.argv", ["grade.py", "--job-dir", str(job)]):
                    status = grader.main()
                result = json_object(
                    json.loads((job / "results/results.json").read_text())
                )
                self.assertEqual(status, 0)
                self.assertIs(result["gradable"], False)
                self.assertIs(result["grading_error"], True)
                self.assertEqual(result["classification"], "infrastructure-failure")
                self.assertNotIn("score", result)
                self.assertNotIn(CANARY, json.dumps(result))
                message = result["message"]
                assert isinstance(message, str)
                self.assertIn("Проверка недоступна", message)

    def test_non_object_descriptor_does_not_admit_scored_projection(self) -> None:
        feedback = load_student_feedback(
            unit_platform(self) / "runtime/student_feedback.py"
        )
        for descriptor in (None, list[object]()):
            with self.subTest(descriptor=descriptor), self.assertRaises(ValueError):
                feedback.student_result(
                    {"classification": "success", "gradable": True, "score": 1},
                    descriptor,
                )
        with self.assertRaises(ValueError):
            feedback.student_result(list[object](), {})
