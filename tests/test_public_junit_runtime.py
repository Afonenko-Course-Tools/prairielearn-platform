"""Публичный JUnit: сообщения, значения и стандартные состояния тестов."""

import runpy
import unittest
import test_plain_runtime as fixtures

ROOT = fixtures.ROOT


class PublicJUnitRuntimeTests(unittest.TestCase):
    setUp = fixtures.PlainRuntimeTests.setUp
    run_job = fixtures.PlainRuntimeTests.run_job

    def test_public_assertion_diagnostics(self):
        (self.job / "student/Student.java").write_text(
            "public class Student { public static int answer(){ return 41; } }"
        )
        result = self.run_job()
        self.assertEqual(result["classification"], "behavior-failure")
        case = result["counts"]["cases"][0]
        self.assertEqual(case["expected"], "42")
        self.assertEqual(case["actual"], "41")
        self.assertIn("expected: <42> but was: <41>", case["message"])
        self.assertIn("AnswerTest.answer", case["stackTrace"])
        self.assertNotIn("checks", case)
        public = runpy.run_path(str(ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, self.config)
        self.assertEqual(public["feedback"]["cases"][0]["actual"], "41")
        self.assertIn("expected: <42>", public["tests"][0]["message"])
