"""Публичный JUnit: сообщения, значения и стандартные состояния тестов."""

import unittest
from pathlib import Path

import test_plain_runtime as fixtures
from grading_types import JavaGradingDescriptor
from platform_modules import load_student_feedback

ROOT = fixtures.ROOT
feedback = load_student_feedback(ROOT / "runtime/student_feedback.py")


class PublicJUnitRuntimeTests(unittest.TestCase):
    job: Path
    config: JavaGradingDescriptor

    setUp = fixtures.PlainRuntimeTests.setUp
    run_job = fixtures.PlainRuntimeTests.run_job

    def test_public_assertion_diagnostics(self) -> None:
        (self.job / "student/Student.java").write_text(
            "public class Student { public static int answer(){ return 41; } }"
        )
        result = self.run_job()
        assert "counts" in result
        self.assertEqual(result["classification"], "behavior-failure")
        case = result["counts"]["cases"][0]
        assert "expected" in case and "actual" in case
        assert "message" in case and "stackTrace" in case
        self.assertEqual(case["expected"], "42")
        self.assertEqual(case["actual"], "41")
        self.assertIn("expected: <42> but was: <41>", case["message"])
        self.assertIn("AnswerTest.answer", case["stackTrace"])
        self.assertNotIn("checks", case)
        public = feedback.student_result(result, self.config)
        assert "cases" in public["feedback"] and "tests" in public
        public_case = public["feedback"]["cases"][0]
        assert "actual" in public_case
        self.assertEqual(public_case["actual"], "41")
        self.assertIn("expected: <42>", public["tests"][0]["message"])
