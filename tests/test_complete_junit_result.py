"""Полный набор JUnit: равные случаи, достоверность событий и ноль попытки."""

import os
import shutil
import json
import runpy
import unittest
from unittest.mock import patch

import test_grading_job as fixtures
import test_api_precheck as api

grader = fixtures.grader


class CompleteJUnitResult(unittest.TestCase):
    setUp = fixtures.JUnitJob.setUp
    run_job = fixtures.JUnitJob.run_job

    def public_result(self, result):
        return runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, self.cfg)

    def test_mutable_throwable_stack_cannot_authorize_subject_values(self):
        for trace in (
            "new StackTraceElement[0]",
            'new StackTraceElement[]{new StackTraceElement("org.junit.jupiter.api.Assertions", "assertEquals", "Assertions.java", 1)}',
        ):
            with self.subTest(trace=trace):
                (self.job / "student/Student.java").write_text(
                    "public class Student {public static int answer(){"
                    'var failure = new org.opentest4j.AssertionFailedError("PRIVATE_THROWABLE_MESSAGE",'
                    '"FORGED_EXPECTED_CANARY",System.getProperty("java.class.path"));'
                    f"failure.setStackTrace({trace});throw failure;}}}}"
                )
                (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @DisplayName("Ответ студента") void result() { assertEquals(42, Student.answer()); }
}""")
                result = self.run_job()
                public = self.public_result(result)
                self.assertEqual(public["score"], 0)
                self.assertEqual(result["counts"]["executed"], 1)
                self.assertEqual(result["counts"]["failed"], 1)
                self.assertEqual(
                    public["feedback"]["cases"],
                    [{"name": "Ответ студента", "status": "failed", "checks": []}],
                )
                for canary in (
                    "FORGED_EXPECTED_CANARY",
                    "PRIVATE_THROWABLE_MESSAGE",
                    "java25-job-runtime-",
                    "junit-platform-console",
                ):
                    self.assertNotIn(canary, json.dumps(public))
                self.assertEqual(
                    public["tests"][0]["description"],
                    "Ожидается: не установлено\nПолучено: не установлено",
                )

    def test_real_typed_assertion_captures_arguments_without_throwable_values(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @DisplayName("Проверка фактических аргументов") void result() { assertEquals(41, Student.answer(), "PRIVATE_ASSERTION_MESSAGE"); }
}""")
        result = self.run_job()
        public = self.public_result(result)
        self.assertEqual(result["classification"], "behavior-failure")
        self.assertEqual(public["score"], 0)
        case = public["feedback"]["cases"][0]
        self.assertEqual(case["name"], "Проверка фактических аргументов")
        self.assertEqual(
            [(c["expected"], c["actual"]) for c in case["checks"]], [("41", "42")]
        )
        self.assertIn("Ожидается: 41", public["tests"][0]["description"])
        self.assertIn("Получено: 42", public["tests"][0]["description"])
        self.assertNotIn("PRIVATE_ASSERTION_MESSAGE", json.dumps(public))

    def test_two_ordinary_and_eight_parameter_rows_have_equal_weight(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @Tag("points=30") @DisplayName("Обычный результат") void ordinary() { assertEquals(42, Student.answer()); }
 @Test @DisplayName("Граничный результат") void boundary() { assertTrue(true); }
 @ParameterizedTest(name="Строка {0}") @ValueSource(ints={0,1,2,3,4,5,6,7})
 void rows(int n) { assertEquals(n, n == 7 ? 8 : n); }
}""")
        result = self.run_job()
        self.assertEqual(result["counts"]["executed"], 10)
        self.assertEqual(result["counts"]["passed"], 9)
        self.assertEqual(result["score"], 0.9)
        self.assertEqual(result["maxPoints"], 10)
        self.assertEqual(len(result["tests"]), 10)

    def test_dynamic_cases_count_but_factory_and_containers_do_not(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import java.util.stream.Stream;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @TestFactory Stream<DynamicTest> dynamic() {
  return Stream.of(DynamicTest.dynamicTest("Первый случай", () -> assertEquals(42, Student.answer())),
                   DynamicTest.dynamicTest("Второй случай", () -> assertEquals(1, 2)));
 }
}""")
        result = self.run_job()
        self.assertEqual(result["score"], 0.5)
        self.assertEqual(result["counts"]["discovered"], 2)
        self.assertEqual(len(result["tests"]), 2)

    def test_own_compile_failure_is_zero_without_invented_cases(self):
        (self.job / "student/Student.java").write_text("not Java")
        result = self.run_job()
        self.assertTrue(result["gradable"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["dependentExecution"], "not-run")
        self.assertNotIn("counts", result)
        self.assertNotIn("tests", result)

    def test_packaged_compiler_error_shows_relative_file_line_and_types(self):
        (self.job / "student/Student.java").unlink()
        (self.job / "student/pkg").mkdir()
        (self.job / "student/pkg/Student.java").write_text(
            'package pkg; public class Student {public static int answer(){return "PRIVATE_SOURCE_CANARY";}}'
        )
        self.cfg["sourceFiles"] = ["pkg/Student.java"]
        result = self.run_job()
        import runpy

        public = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, self.cfg)
        self.assertEqual(
            public["feedback"]["compileErrors"],
            [
                {
                    "file": "pkg/Student.java",
                    "line": 1,
                    "reason": "Нельзя преобразовать String в int.",
                }
            ],
        )
        self.assertEqual(public["score"], 0)
        self.assertNotIn("PRIVATE_SOURCE_CANARY", json.dumps(public))
        self.assertNotIn("/grade", json.dumps(public))

    def test_executor_kill_cannot_establish_a_complete_zero(self):
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){while(true){}}}"
        )
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_missing_duplicate_and_inconsistent_event_records_are_rejected(self):
        original = grader._run

        def corrupt(command, *args, **kwargs):
            result = original(command, *args, **kwargs)
            if "PlatformJUnitAdapter" in command:
                # Fresh private reports only; mutation models a broken producer,
                # never student access to params or report paths.
                params_path = fixtures.Path(command[-1])
                for path in params_path.parent.parent.glob("results/*.json"):
                    value = json.loads(path.read_text())
                    if "outcomes" in value:
                        if mutation == "discovery":
                            value["discovered"] += 1
                        elif mutation == "executed":
                            value["executed"] += 1
                        elif mutation == "missing":
                            value["outcomes"].clear()
                        elif mutation == "duplicate":
                            key = next(iter(value["outcomes"]))
                            text = json.dumps(value)
                            text = text.replace(
                                '"outcomes": {',
                                '"outcomes": {' + json.dumps(key) + ': "successful",',
                                1,
                            )
                            path.write_text(text)
                            continue
                        elif mutation == "unfinished":
                            value["complete"] = False
                        elif mutation == "foreign":
                            value["signature"] = "0" * 64
                        elif mutation == "registered-duplicate":
                            value["registered"].append(value["registered"][0])
                        elif mutation == "malformed":
                            path.write_text("{")
                            continue
                        path.write_text(json.dumps(value))
            return result

        for mutation in (
            "discovery",
            "executed",
            "missing",
            "duplicate",
            "unfinished",
            "foreign",
            "registered-duplicate",
            "malformed",
        ):
            with self.subTest(mutation=mutation), patch.object(
                grader, "_run", side_effect=corrupt
            ):
                with self.assertRaises(grader.GraderError):
                    self.run_job()

    @unittest.skipUnless(
        os.environ.get("JAVA_CONSOLE_SUPPORT"),
        "Требуется канонический JavaProcess.java",
    )
    def test_observed_case_timeout_preserves_other_case_credit(self):
        helper = self.job / "tests/coursesupport/JavaProcess.java"
        helper.parent.mkdir()
        shutil.copyfile(os.environ["JAVA_CONSOLE_SUPPORT"], helper)
        self.cfg["testFiles"].append("coursesupport/JavaProcess.java")
        self.cfg["limits"]["run-seconds"] = 10
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){return 42;} public static void main(String[] args){while(true){}}}"
        )
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @DisplayName("Обычный случай") void ordinary() { assertEquals(42, Student.answer()); }
 @Test @DisplayName("Отдельный запуск ограничен временем") void timeout() throws Exception {
  var root = java.nio.file.Path.of(Student.class.getProtectionDomain().getCodeSource().getLocation().toURI());
  coursesupport.JavaProcess.run(root, "Student", "", java.util.List.of(), null, java.time.Duration.ofMillis(100), 65536);
 }
}""")
        result = self.run_job()
        self.assertEqual(result["classification"], "student-timeout")
        self.assertEqual(result["score"], 0.5)
        self.assertEqual(
            (result["counts"]["passed"], result["counts"]["failed"]), (1, 1)
        )
        import test_review_receipts as review

        bound = review.result()
        bound.update(result)
        bound["backend"] = "host"
        review.g.validate("check-result", bound)

    def test_full_feedback_has_subject_values_without_private_exception_noise(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @DisplayName("Ответ равен ожидаемому") void result(TestReporter reporter) { int actual = Student.answer(); reporter.publishEntry(java.util.Map.of("expected","41","actual",String.valueOf(actual))); assertEquals(41, actual, "PRIVATE_TRACE_CANARY"); }
 @Test @DisplayName("Обычный случай") void normal(TestReporter reporter) { reporter.publishEntry(java.util.Map.of("expected","42","actual",String.valueOf(Student.answer()))); assertEquals(42, Student.answer()); }
}""")
        result = self.run_job()
        import runpy

        public = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, self.cfg)
        self.assertEqual(public["score"], 0.5)
        cases = public["feedback"]["cases"]
        self.assertEqual(len(cases), 2)
        failed = next(case for case in cases if case["status"] == "failed")
        self.assertEqual(
            (failed["name"], failed["expected"], failed["actual"]),
            ("Ответ равен ожидаемому", "41", "42"),
        )
        passed = next(case for case in cases if case["status"] == "passed")
        self.assertEqual(
            (passed["name"], passed["expected"], passed["actual"]),
            ("Обычный случай", "42", "42"),
        )
        self.assertTrue(
            all("не установлено" not in case["description"] for case in public["tests"])
        )
        self.assertNotIn("PRIVATE_TRACE_CANARY", json.dumps(public))


class AdmissionZero(unittest.TestCase):
    setUp = api.ApiPrecheckTests.setUp
    check = api.ApiPrecheckTests.check
    run_job = fixtures.JUnitJob.run_job

    def test_api_failure_is_zero_with_not_run_dependent_tests(self):
        (self.job / "student/Student.java").write_text("public class Student {}")
        result = self.run_job()
        self.assertTrue(result["gradable"])
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["apiPrecheck"], "failure")
        self.assertEqual(result["dependentExecution"], "not-run")
        self.assertNotIn("counts", result)
        self.assertNotIn("tests", result)


class CompleteReportBoundary(unittest.TestCase):
    def test_empty_case_feedback_cannot_claim_complete_implementation_run(self):
        counts = {
            "discovered": 1,
            "executed": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "aborted": 0,
            "containerFailures": 0,
            "eventErrors": 0,
            "complete": True,
            "outcomes": {"case": "successful"},
            "registered": ["case"],
            "started": ["case"],
            "failureKinds": {},
            "cases": [],
        }
        with self.assertRaises(grader.GraderError):
            grader._validate_junit_counts(counts)

    def test_compile_feedback_identifies_own_source_line_without_source_or_paths(self):
        import runpy

        result = {
            "classification": "student-compilation-failure",
            "gradable": True,
            "score": 0,
            "diagnostics": {
                "studentCompilation": "/grade/student/Student.java:3: error: cannot find symbol\nreturn PRIVATE_SOURCE_CANARY;\n       ^\n"
            },
        }
        public = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, {})
        self.assertTrue(public["gradable"])
        self.assertEqual(public["score"], 0)
        self.assertEqual(
            public["feedback"]["compileErrors"],
            [
                {
                    "file": "Student.java",
                    "line": 3,
                    "reason": "Не найден используемый тип, метод или переменная.",
                }
            ],
        )
        self.assertNotIn("PRIVATE_SOURCE_CANARY", json.dumps(public))
        self.assertNotIn("/grade", json.dumps(public))
        self.assertNotIn("format_errors", public)


class CompilerRelativePath(unittest.TestCase):
    def test_compiler_diagnostic_preserves_logical_nested_submission_path(self):
        import runpy

        result = {
            "classification": "student-compilation-failure",
            "gradable": True,
            "score": 0,
            "diagnostics": {
                "studentCompilation": "/grade/student/pkg/Student.java:7: error: incompatible types: java.lang.String cannot be converted to int\nPRIVATE_SOURCE_CANARY\n"
            },
        }
        public = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, {"sourceFiles": ["pkg/Student.java"]})
        self.assertEqual(
            public["feedback"]["compileErrors"],
            [
                {
                    "file": "pkg/Student.java",
                    "line": 7,
                    "reason": "Нельзя преобразовать java.lang.String в int.",
                }
            ],
        )
        self.assertNotIn("/grade", json.dumps(public))
        self.assertNotIn("PRIVATE_SOURCE_CANARY", json.dumps(public))


class SharedRuntimeCompatibility(unittest.TestCase):
    def test_fish_syntax_projection_keeps_existing_ungradable_submission_contract(self):
        import runpy

        result = {
            "classification": "student-compilation-failure",
            "gradable": False,
            "studentCompilation": "failure",
            "trustedCompilation": "not-run",
            "infrastructure": "complete",
            "format_errors": "Ошибка синтаксиса fish",
            "output": "",
        }
        public = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ](result, {"runtime": "fish-git-v1"})
        self.assertFalse(public["gradable"])
        self.assertNotIn("score", public)
        import test_compiled_inventory_schema as schema

        value = schema.envelope(result, "fish-git-v1")
        schema.jsonschema.Draft202012Validator(schema.SCHEMA).validate(value)


class ReceiptResultAdmission(unittest.TestCase):
    def test_receipt_boundary_rejects_legacy_missing_terminal_event_evidence(self):
        import test_review_receipts as review

        value = review.result()
        for key in (
            "complete",
            "eventErrors",
            "registered",
            "started",
            "failureKinds",
            "cases",
        ):
            value["counts"].pop(key)
        with self.assertRaises(review.g.JobError):
            review.g.validate("check-result", value)

    def test_receipt_boundary_rejects_inconsistent_counts_and_weighted_fraction(self):
        import test_review_receipts as review

        value = review.result()
        value["counts"].update(
            complete=True,
            eventErrors=0,
            registered=["T#t"],
            started=["T#t"],
            failureKinds={},
            cases=[{"id": "T#t", "name": "Проверка результата", "status": "passed"}],
        )
        for mutation in ("discovery", "fraction", "public"):
            changed = __import__("copy").deepcopy(value)
            if mutation == "discovery":
                changed["counts"]["discovered"] = 2
            elif mutation == "fraction":
                changed["score"] = 0.5
            else:
                excluded = {
                    "schemaVersion",
                    "scope",
                    "backend",
                    "qualifiedId",
                    "scenario",
                    "sourceSnapshotHash",
                    "inventoryHash",
                    "deliveryHash",
                    "runtime",
                    "imageDigest",
                    "sourceHashes",
                    "testsHashes",
                }
                changed["publicResult"] = {
                    key: item
                    for key, item in __import__("copy").deepcopy(value).items()
                    if key not in excluded
                }
                changed["publicResult"]["counts"]["executed"] = 2
            with self.subTest(mutation=mutation), self.assertRaises(review.g.JobError):
                review.g.validate("check-result", changed)
