"""Обычные AssertionError: диагностика выполнения и результаты проверок."""

import os
import unittest
import test_grading_job as fixtures
import test_plain_image as image_fixtures
from test_student_feedback import feedback


class DirectAssertionTests(unittest.TestCase):
    def fixture(self, student, tests=fixtures.TEST):
        value = fixtures.JUnitJob()
        value.setUp()
        self.addCleanup(value.doCleanups)
        (value.job / "student/Student.java").write_text(student)
        (value.job / "tests/AnswerTest.java").write_text(tests)
        return value

    def test_inner_and_secondary_student_assertions_report_runtime_errors(self):
        for source, message in [
            (
                'public class Student {static class Inner {static int value(){throw new AssertionError("вложенный класс");}} public static int answer(){return Inner.value();}}',
                "вложенный класс",
            ),
            (
                'class Secondary {static int value(){throw new AssertionError("дополнительный класс");}} public class Student {public static int answer(){return Secondary.value();}}',
                "дополнительный класс",
            ),
        ]:
            with self.subTest(message=message):
                fixture = self.fixture(source)
                result = fixture.run_job()
                native = feedback.student_result(result, fixture.cfg)
                self.assertEqual(native["feedback"]["kind"], "runtime")
                self.assertEqual(native["score"], 0)
                case = native["feedback"]["cases"][0]
                self.assertIn(message, case["message"])
                self.assertEqual(case["exceptionType"], "java.lang.AssertionError")
                self.assertIn("Student.java:1", case["stackTrace"])
                self.assertNotIn("teacherTrace", case)

    def test_test_assertion_and_swallowed_student_error_are_behavior_failures(self):
        for source, tests in [
            (
                'public class Student {public static int answer(){try{throw new AssertionError("перехвачено");}catch(AssertionError ignored){return 0;}}}',
                fixtures.TEST,
            ),
            (
                "public class Student {public static int answer(){return 42;}}",
                'import org.junit.jupiter.api.Test;public class AnswerTest {@Test void wrong(){throw new AssertionError("проверка поведения");}}',
            ),
        ]:
            with self.subTest(source=source):
                fixture = self.fixture(source, tests)
                result = fixture.run_job()
                native = feedback.student_result(result, fixture.cfg)
                self.assertEqual(native["feedback"]["kind"], "wrong-answer")
                self.assertEqual(native["score"], 0)
                self.assertEqual(result["counts"]["failed"], 1)
                self.assertEqual(native["feedback"]["cases"][0]["status"], "failed")

    def test_student_tests_still_reject_a_mutant(self):
        fixture = fixtures.MutationJob()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_mutation()
        result = fixture.run_job()
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["classification"], "success")
        self.assertEqual(result["variants"]["correct"]["counts"]["passed"], 1)
        self.assertEqual(result["variants"]["wrong"]["counts"]["failed"], 1)


@unittest.skipUnless(os.environ.get("PL_TEST_IMAGE"), "Нужен собранный PL_TEST_IMAGE")
class DirectAssertionContainer(unittest.TestCase):
    def test_official_sandbox_reports_ordinary_assertion_diagnostics(self):
        fixture = fixtures.JUnitJob()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.job / "student/Student.java").write_text(
            'public class Student {static class Inner {static int value(){throw new AssertionError("вложенный класс");}}public static int answer(){return Inner.value();}}'
        )
        image = image_fixtures.PlainImageTests()
        self.addCleanup(image.doCleanups)
        image.job, image.config = fixture.job, fixture.cfg
        run, result = image.invoke(cpus="0.9", verification=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(result["feedback"]["kind"], "runtime")
        self.assertEqual(result["feedback"]["cases"][0]["message"], "вложенный класс")
        self.assertNotIn("teacherTrace", result["feedback"]["cases"][0])
        self.assertNotIn("counts", result)
