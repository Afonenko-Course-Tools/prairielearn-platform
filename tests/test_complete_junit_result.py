"""Обычные завершённые и прерванные исполнения публичного JUnit."""

import unittest
from pathlib import Path

import test_plain_runtime as fixtures
from grading_types import JavaGradingDescriptor
from platform_modules import load_student_feedback

ROOT = fixtures.ROOT
feedback = load_student_feedback(ROOT / "runtime/student_feedback.py")
grader = fixtures.grader


class CompleteJUnitResult(unittest.TestCase):
    job: Path
    config: JavaGradingDescriptor

    setUp = fixtures.PlainRuntimeTests.setUp
    run_job = fixtures.PlainRuntimeTests.run_job

    def source(self, body: str) -> None:
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest {"
            + body
            + "}"
        )

    def test_abort_does_not_produce_a_score(self) -> None:
        self.source('@Test void abort(){ Assumptions.assumeTrue(false, "пропуск"); }')
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_disabled_test_does_not_produce_a_score(self) -> None:
        self.source(
            '@Test @Disabled("пропуск") void disabled(){} @Test void active(){}'
        )
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_exception_has_public_message_and_private_full_trace(self) -> None:
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){throw new IllegalStateException("учебная ошибка");}}'
        )
        result = self.run_job()
        assert "counts" in result
        self.assertEqual(result["classification"], "student-runtime-failure")
        case = result["counts"]["cases"][0]
        assert "message" in case and "exceptionType" in case
        assert "stackTrace" in case and "teacherTrace" in case
        self.assertEqual(case["message"], "учебная ошибка")
        self.assertEqual(case["exceptionType"], "java.lang.IllegalStateException")
        self.assertIn("Student.answer", case["stackTrace"])
        self.assertIn("org.junit", case["teacherTrace"])
        native = feedback.student_result(result, self.config)
        assert "cases" in native["feedback"]
        public_case = native["feedback"]["cases"][0]
        assert "message" in public_case
        self.assertEqual(public_case["message"], "учебная ошибка")
        self.assertNotIn("teacherTrace", native["feedback"]["cases"][0])

    def test_student_initializer_failure_is_runtime_failure(self) -> None:
        (self.job / "student/Student.java").write_text("""public class Student {
    static int value = init();
    static int init() { throw new IllegalStateException("initializer"); }
    public static int answer() { return value; }
}""")
        result = self.run_job()
        assert "counts" in result
        self.assertEqual(result["classification"], "student-runtime-failure")
        case = result["counts"]["cases"][0]
        assert "teacherTrace" in case
        self.assertIn("initializer", case["teacherTrace"])
        native = feedback.student_result(result, self.config)
        assert "cases" in native["feedback"]
        case = native["feedback"]["cases"][0]
        assert "message" in case and "stackTrace" in case
        self.assertIn("initializer", case["message"])
        self.assertIn("java.lang.IllegalStateException", case["message"])
        self.assertIn("Student.init(Student.java:3)", case["stackTrace"])
        self.assertNotIn("teacherTrace", case)

    def test_successful_assertions_are_not_traced(self) -> None:
        self.source(
            "@Test void success(){ assertEquals(42,Student.answer()); assertTrue(true); }"
        )
        result = self.run_job()
        assert "counts" in result
        case = result["counts"]["cases"][0]
        self.assertEqual(case["status"], "passed")
        for key in ("checks", "expected", "actual", "teacherTrace"):
            self.assertNotIn(key, case)

    def test_output_is_bounded_and_available(self) -> None:
        self.source(
            '@Test void output(){System.out.print("stdout пример"); System.err.print("stderr пример"); assertEquals(42,Student.answer());}'
        )
        result = self.run_job()
        assert "counts" in result
        public = feedback.student_result(result, self.config)
        assert "output" in public
        self.assertIn("stdout пример", public["output"])
        self.assertIn("stderr пример", public["output"])
        self.assertLessEqual(len(public["output"].encode("utf-8")), 65536)

    def test_test_reporter_values_are_available(self) -> None:
        self.source(
            '@Test void reports(TestReporter reporter){ reporter.publishEntry(java.util.Map.of("expected","API контракт","actual","наблюдение")); }'
        )
        result = self.run_job()
        assert "counts" in result
        case = result["counts"]["cases"][0]
        assert "expected" in case and "actual" in case
        self.assertEqual(
            (case["expected"], case["actual"]), ("API контракт", "наблюдение")
        )
