"""C3-1: настоящий production путь assertion → counts → native feedback."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import runpy
import unittest
from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict, runtime_checkable
from platform_modules import load_student_feedback
from grading_types import JavaGradingDescriptor, JavaOutcome, PublicCase, PublicTest, StudentResult
if TYPE_CHECKING:
    from junit_result import AssertionCheck, JUnitCase, JUnitCounts
from json_boundary import is_object
import test_grading_job as fixtures

@runtime_checkable
class CountsValidator(Protocol):
    def __call__(self, counts: object, require_cases: bool = True) -> None: ...


@runtime_checkable
class GraderRun(Protocol):
    def __call__(self, command: Sequence[str], cwd: Path, timeout: float,
                 output_limit: int = 65536, *, env: Mapping[str, str] | None = None
                 ) -> tuple[int, str, Literal["timeout", "output_limit"] | None]: ...


def grader_run() -> GraderRun:
    value: object = getattr(fixtures.grader, "_run")
    if not isinstance(value, GraderRun):
        raise RuntimeError("Частный callback grader _run недоступен")
    return value


_validator: object = runpy.run_path(str(fixtures.ROOT / "runtime/junit_result.py"))["validate_counts"]
if not isinstance(_validator, CountsValidator):
    raise RuntimeError("Контракт validate_counts недоступен")
validate_counts = _validator
feedback = load_student_feedback(fixtures.ROOT / "runtime/student_feedback.py").student_result


def case_checks(case: JUnitCase) -> list[AssertionCheck]:
    assert "checks" in case
    return case["checks"]


def result_counts(result: JavaOutcome) -> JUnitCounts:
    assert "counts" in result
    return result["counts"]


def public_tests(result: StudentResult) -> list[PublicTest]:
    assert "tests" in result
    return result["tests"]


def public_cases(result: StudentResult) -> list[PublicCase]:
    public_feedback = result["feedback"]
    assert "cases" in public_feedback
    return public_feedback["cases"]


def public_score(result: StudentResult) -> float:
    assert "score" in result
    return result["score"]


def completeness(result: StudentResult) -> str:
    public_feedback = result["feedback"]
    assert "feedbackCompleteness" in public_feedback
    return public_feedback["feedbackCompleteness"]


CheckTextField = Literal["delta", "differenceIndex", "differenceLine", "differenceColumn",
                         "differenceExpected", "differenceActual"]


def check_text(check: AssertionCheck, key: CheckTextField) -> str:
    value = check.get(key)
    assert value is not None
    return value


class PreservedInput(TypedDict):
    sha256: str
    bytes: int


class BrokenProducer(TypedDict):
    beforeSha256: str
    afterSha256: str
    mutation: str
    operatorAuthenticatedBrokenProducer: bool


class CallReceipt(TypedDict):
    compiledBefore: dict[str, str]
    compiledAfter: dict[str, str]
    sealedObserver: dict[str, str]
    consumedParams: PreservedInput | None
    signedReports: dict[str, str]
    jars: dict[str, str]
    argv: list[str]
    seconds: float
    exitCode: int
    reason: Literal["timeout", "output_limit"] | None
    outputSha256: str
    brokenProducer: NotRequired[BrokenProducer]


class JobCase(unittest.TestCase):
    job: Path
    cfg: JavaGradingDescriptor

    def setUp(self) -> None:
        self.fixture = fixtures.JUnitJob(methodName="runTest")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.job = self.fixture.job
        self.cfg = self.fixture.cfg

    def run_job(self) -> JavaOutcome:
        self.fixture.cfg = self.cfg
        return self.fixture.run_job()


class ProductionCase(JobCase):
    calls: list[CallReceipt]

    def run_job(self) -> JavaOutcome:
        result = super().run_job()
        destination = os.environ.get("C3_PRODUCT_RECEIPTS")
        if destination:
            out = Path(destination)
            out.mkdir(parents=True, exist_ok=True)
            (out / (self._testMethodName + "-result.json")).write_text(
                json.dumps(
                    {"result": result, "native": feedback(result, self.cfg)},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        return result

    def preserve(self, path: Path) -> str:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        destination = os.environ.get("C3_PRODUCT_RECEIPTS")
        if destination:
            blobs = Path(destination) / "generated"
            blobs.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = blobs / digest
            if target.exists():
                self.assertEqual(target.read_bytes(), content)
            else:
                with target.open("xb") as output:
                    output.write(content)
                target.chmod(0o600)
        return digest

    def setUp(self) -> None:
        super().setUp()
        self.calls = []
        original = grader_run()

        def measured(command: Sequence[str], cwd: Path, timeout: float,
                     output_limit: int = 65536, *, env: Mapping[str, str] | None = None
                     ) -> tuple[int, str, Literal["timeout", "output_limit"] | None]:
            started = time.monotonic()
            before: dict[str, str] = {}
            transform_root: Path | None = None
            parameter_file: Path | None = None
            if "Transform" in command:
                transform_root = Path(command[command.index("Transform") + 1])
                if transform_root.is_dir():
                    before = {
                        str(p.relative_to(transform_root)): self.preserve(p)
                        for p in transform_root.rglob("*.class")
                    }
            sealed: dict[str, str] = {}
            params: PreservedInput | None = None
            reports: dict[str, str] = {}
            jars: dict[str, str] = {}
            if any(arg.endswith("PlatformJUnitAdapter") for arg in command) and "--module-path" in command:
                module = Path(
                    command[command.index("--module-path") + 1].split(os.pathsep)[0]
                )
                sealed = {
                    str(p.relative_to(module)): self.preserve(p)
                    for p in module.rglob("*")
                    if p.is_file()
                }
                parameter_file = Path(command[-1])
                params = {
                    "sha256": self.preserve(parameter_file),
                    "bytes": parameter_file.stat().st_size,
                }
                for element in command[command.index("--module-path") + 1].split(
                    os.pathsep
                ):
                    dependency = Path(element)
                    if dependency.is_file():
                        jars[dependency.name] = self.preserve(dependency)
            result = original(command, cwd, timeout, output_limit, env=env)
            if params is not None:
                assert parameter_file is not None
                reports = {
                    p.name: self.preserve(p)
                    for p in parameter_file.parent.parent.joinpath("results").glob(
                        "*.json"
                    )
                }

            after: dict[str, str] = {}
            if before:
                assert transform_root is not None
                after = {
                    str(p.relative_to(transform_root)): self.preserve(p)
                    for p in transform_root.rglob("*.class")
                }
            self.calls.append(
                {
                    "compiledBefore": before,
                    "compiledAfter": after,
                    "sealedObserver": sealed,
                    "consumedParams": params,
                    "signedReports": reports,
                    "jars": jars,
                    "argv": [str(x) for x in command],
                    "seconds": time.monotonic() - started,
                    "exitCode": result[0],
                    "reason": result[2],
                    "outputSha256": hashlib.sha256(result[1].encode()).hexdigest(),
                }
            )
            return result

        self.enterContext(patch.object(fixtures.grader, "_run", measured))
        self.addCleanup(self.save_execution)

    def save_execution(self) -> None:
        destination = os.environ.get("C3_PRODUCT_RECEIPTS")
        if not destination:
            return
        out = Path(destination)
        out.mkdir(parents=True, exist_ok=True)
        (out / (self._testMethodName + "-execution.json")).write_text(
            json.dumps(
                {
                    "calls": self.calls,
                    "env": {
                        key: os.environ.get(key)
                        for key in (
                            "XDG_CACHE_HOME",
                            "GRADLE_USER_HOME",
                            "JAVA_HOME",
                            "JAVA_EARLY_PROJECTS",
                        )
                    },
                    "fixtures": {
                        str(p.relative_to(self.job)): self.preserve(p)
                        for name in ("student", "tests")
                        for p in (self.job / name).rglob("*")
                        if p.is_file()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


class AssertionFeedback(ProductionCase):

    def test_ordinary_junit_keeps_real_leaves_and_private_failure_details(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @ParameterizedTest(name="Самостоятельный случай {0}") @ValueSource(ints={1,2})
 void rows(int n){assertEquals((double)n,(double)n,"PRIVATE_PARAMETER_MESSAGE");}
 @Test @DisplayName("Обычное равенство") void exact(){
  assertEquals(187.25d,Student.answer(),"PRIVATE_DOUBLE_MESSAGE");
 }
 @Test @DisplayName("Две причины одного случая") void grouped(){
  assertAll("PRIVATE_GROUP_MESSAGE",
   ()->assertEquals(41,Student.answer(),"PRIVATE_FIRST_MESSAGE"),
   ()->assertTrue(false,"PRIVATE_SECOND_MESSAGE"));
 }
 @Test @DisplayName("Равенство с допуском") void tolerance(){
  assertEquals(41d,Student.answer(),0.01d,"PRIVATE_TOLERANCE_MESSAGE");
 }
 @Test @DisplayName("Успех без обязательного наблюдения") void lazy(){
  assertEquals(42d,Student.answer(),()->{throw new IllegalStateException("EAGER_MESSAGE");});
  assertArrayEquals(new boolean[]{true},new boolean[]{true});
 }
}
""")
        result = self.run_job()
        assert "score" in result
        counts = result_counts(result)
        self.assertEqual((counts["executed"], counts["passed"], counts["failed"]), (6, 3, 3))
        self.assertTrue(counts["complete"])
        self.assertEqual(result["score"], 0.5)
        cases = counts["cases"]
        group = next(c for c in cases if c["name"] == "Две причины одного случая")
        self.assertEqual(len(case_checks(group)), 2)
        self.assertTrue(all(c["delegated"] == "threw" for c in case_checks(group)))
        lazy = next(c for c in cases if c["name"] == "Успех без обязательного наблюдения")
        self.assertEqual(lazy["status"], "passed")
        self.assertEqual(len(case_checks(lazy)), 2)
        self.assertTrue(all(check["delegated"] == "returned" and check["availability"] == "complete" for check in case_checks(lazy)))
        assert "rawResult" in result
        raw_cases = result["rawResult"]["tests"]
        raw_group = next(c for c in raw_cases if c["name"] == "Две причины одного случая")
        self.assertEqual(raw_group["message"], "")
        raw_exact = next(c for c in raw_cases if c["name"] == "Обычное равенство")
        self.assertEqual(raw_exact["message"], "")
        native = feedback(result, self.cfg)
        self.assertEqual((public_score(native), len(public_tests(native))), (0.5, 6))
        tolerance = next(t for t in public_tests(native) if t["name"] == "Равенство с допуском")
        self.assertIn("Допуск: 0.01", tolerance["message"])
        public = json.dumps(native, ensure_ascii=False)
        for private in ("PRIVATE_", "EAGER_MESSAGE", "java25-job-runtime-"):
            self.assertNotIn(private, public)

    def test_real_arguments_reach_native_without_new_points(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test @DisplayName("Фактический ответ") void result(TestReporter reporter) {
   assertEquals(42,Student.answer());
   reporter.publishEntry(java.util.Map.of("expected","Отдельное ожидание","actual","Отдельное наблюдение"));
   assertEquals(41,Student.answer(),"PRIVATE_ASSERTION_MESSAGE");
 }
}""")
        result = self.run_job()
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (1, 0)
        )
        checks = result_counts(result)["cases"][0].get("checks", [])
        self.assertEqual(
            [(c["expected"], c["actual"]) for c in checks], [("42", "42"), ("41", "42")]
        )
        native = feedback(result, self.cfg)
        self.assertEqual(public_score(native), 0)
        self.assertEqual(len(public_tests(native)), 1)
        case = public_cases(native)[0]
        self.assertEqual(
            case.get("reporter"),
            {
                "origin": "trusted-TestReporter",
                "expected": "Отдельное ожидание",
                "actual": "Отдельное наблюдение",
            },
        )
        self.assertIn("Ожидается: 41", public_tests(native)[0]["message"])
        self.assertNotIn("PRIVATE_ASSERTION_MESSAGE", str(native))

    def test_string_difference_beyond_10240_lines_is_localized(self) -> None:
        (self.job / "student/Student.java").write_text(
            'public class Student {public static String answer(){return "строка\\n".repeat(12000)+"Б";}}'
        )
        (self.job / "tests/AnswerTest.java").write_text(
            'import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test @DisplayName("Длинная строка") void result(){assertEquals("строка\\n".repeat(12000)+"А",Student.answer());}}'
        )
        result = self.run_job()
        assert "score" in result
        checks = result_counts(result)["cases"][0].get("checks", [])
        self.assertEqual(len(checks), 1)
        check = checks[0]
        self.assertEqual(
            (
                check_text(check, "differenceIndex"),
                check_text(check, "differenceLine"),
                check_text(check, "differenceColumn"),
            ),
            ("84000", "12001", "1"),
        )
        self.assertIn("А", check_text(check, "differenceExpected"))
        self.assertIn("Б", check_text(check, "differenceActual"))
        self.assertLess(len(str(feedback(result, self.cfg))), 40000)

    def test_measured_byte_difference_after_10240(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {@Test @DisplayName("Дальнее различие байтов") void result(){
 byte[] expected=new byte[12000],actual=expected.clone();actual[11017]=42;
 assertArrayEquals(expected,actual);
}}""")
        result = self.run_job()
        assert "score" in result
        check = case_checks(result_counts(result)["cases"][0])[0]
        self.assertEqual(check_text(check, "differenceIndex"), "11017")
        self.assertEqual(
            (check_text(check, "differenceExpected"), check_text(check, "differenceActual")), ("00", "2a")
        )
        self.assertEqual(public_score(feedback(result, self.cfg)), 0)
        self.assertEqual(result_counts(result)["executed"], 1)

    def test_callback_supplier_timeout_and_opaque_delegate_once(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;
import java.time.Duration;import java.util.concurrent.atomic.AtomicInteger;
public class AnswerTest {
 static int messageCalls,expressionCalls,predicateCalls,callbackCalls,equalsCalls,toStringCalls;
 static final class Opaque {
  public boolean equals(Object other){equalsCalls++;return true;}
  public String toString(){toStringCalls++;return "PRIVATE_OPAQUE_TEXT";}
 }
 static int value(){expressionCalls++;return Student.answer();}
 @Test @DisplayName("Единственный настоящий делегат") void result(){
  assertEquals(42,value(),()->{messageCalls++;return "PRIVATE_LAZY_MESSAGE";});
  assertTrue(()->{predicateCalls++;return true;});
  var thrown=assertThrows(IllegalArgumentException.class,()->{callbackCalls++;throw new IllegalArgumentException();});
  assertNotNull(thrown);
  assertTimeoutPreemptively(Duration.ofSeconds(1),()->{assertEquals(43,Student.answer()+1);});
  assertEquals(new Opaque(),new Opaque());
  if(messageCalls!=0||expressionCalls!=1||predicateCalls!=1||callbackCalls!=1||equalsCalls!=1||toStringCalls!=0)
    throw new AssertionError("extra evaluation");
 }
}""")
        result = self.run_job()
        assert "score" in result
        self.assertEqual(result["score"], 1)
        checks = case_checks(result_counts(result)["cases"][0])
        self.assertTrue(
            any(
                c["expected"] == "43"
                and c["actual"] == "43"
                and c["site"].startswith("AnswerTest.java:")
                for c in checks
            )
        )
        self.assertTrue(any("unsupported" in c["availability"] for c in checks))
        native = feedback(result, self.cfg)
        self.assertEqual(completeness(native), "incomplete")
        for text in ("PRIVATE_OPAQUE_TEXT", "PRIVATE_LAZY_MESSAGE"):
            self.assertNotIn(text, str(native))

    def test_no_argument_fail_preserves_one_native_leaf(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void result(){fail();}}"
        )
        result = self.run_job()
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["failed"]), (1, 1)
        )
        self.assertEqual(public_score(feedback(result, self.cfg)), 0)

    def test_overflow_preserves_delegate_score_and_marks_incomplete(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test void checks(){for(int i=0;i<100;i++)assertEquals(i,i);}
 @Test void snapshots(){byte[] bytes=new byte[40000];assertArrayEquals(bytes,bytes.clone());}
 @Test void stringScan(){assertEquals("x".repeat(1100000),"x".repeat(1100000));}
}""")
        result = self.run_job()
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (3, 3)
        )
        self.assertEqual(result["score"], 1)
        cases = result_counts(result)["cases"]
        check_quota = next(c for c in cases if "checks()" in c["id"])
        self.assertEqual(len(case_checks(check_quota)), 64)
        self.assertEqual(
            case_checks(check_quota)[-1]["availability"], "incomplete: check quota"
        )
        scan = case_checks(next(c for c in cases if "stringScan()" in c["id"]))[0]
        self.assertEqual(
            scan["availability"], "incomplete: string difference scan quota"
        )
        self.assertNotIn("differenceIndex", scan)
        self.assertEqual(
            completeness(feedback(result, self.cfg)), "incomplete"
        )

    def test_student_helper_reentry_has_no_observation_authority(self) -> None:
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){try{Class.forName("AnswerTest").getMethod("helper").invoke(null);}catch(Exception error){throw new RuntimeException(error);}return 42;}}'
        )
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {public static void helper(){assertEquals(7,7);}@Test void result(){assertEquals(42,Student.answer());}}"
        )
        result = self.run_job()
        assert "score" in result
        self.assertEqual(result["score"], 1)
        checks = case_checks(result_counts(result)["cases"][0])
        self.assertEqual([(c["expected"], c["actual"]) for c in checks], [("42", "42")])

    def test_late_preemptive_worker_cannot_change_published_leaf(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;import java.time.Duration;
public class AnswerTest {
 @Test @DisplayName("Истёкший leaf") void late(){assertTimeoutPreemptively(Duration.ofMillis(20),()->{
   long until=System.nanoTime()+150_000_000L;while(System.nanoTime()<until)Thread.onSpinWait();assertEquals(7,7);
 });}
 @Test @DisplayName("Следующий leaf") void next() throws Exception {Thread.sleep(200);assertEquals(42,Student.answer());}
}""")
        result = self.run_job()
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (2, 1)
        )
        cases = result_counts(result)["cases"]
        self.assertFalse(
            any(c["expected"] == "7" for case in cases for c in case_checks(case))
        )
        native = feedback(result, self.cfg)
        self.assertEqual(public_score(native), 0.5)
        self.assertEqual(len(public_tests(native)), 2)


class ActualEarlyFeedback(ProductionCase):

    def early_job(self, project: str, student: str, faulty: bool = False) -> tuple[JavaOutcome, StudentResult]:
        source = os.environ.get("JAVA_EARLY_PROJECTS")
        if not source:
            self.skipTest("JAVA_EARLY_PROJECTS задаёт принятый D1 source")
        source = Path(source)
        unit = source / "projects" / project
        for path in (self.job / "student").glob("*.java"):
            path.unlink()
        for path in (self.job / "tests").glob("*.java"):
            path.unlink()
        copied: dict[str, str] = {}

        def put(path: Path, target: Path) -> None:
            content = path.read_bytes()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            copied[str(path.relative_to(source))] = hashlib.sha256(content).hexdigest()

        put(
            unit / f"reference/src/main/java/{student}.java",
            self.job / f"student/{student}.java",
        )
        for path in (unit / "checks/src/test/java").rglob("*.java"):
            put(
                path,
                self.job / "tests" / path.relative_to(unit / "checks/src/test/java"),
            )
        put(
            unit / "api/src/api/java/ApiContract.java",
            self.job / "tests/ApiContract.java",
        )
        if project == "arrays/reverse-array":
            put(
                source
                / "projects/common/java/process/src/test/java/coursesupport/JavaProcess.java",
                self.job / "tests/coursesupport/JavaProcess.java",
            )
        else:
            self.assertEqual(
                copied[
                    "projects/objects/book-selection/checks/src/test/java/BookSelectionTest.java"
                ],
                "8e5bf83de1ee7332d0fdb03474407949677be51bc6ee4035fc0b866c210ae719",
            )
        self.cfg.update(
            sourceFiles=[student + ".java"],
            testFiles=[
                str(p.relative_to(self.job / "tests"))
                for p in (self.job / "tests").rglob("*.java")
            ],
            apiPrecheck={"files": ["ApiContract.java"], "entry": "ApiContract"},
        )
        if faulty:
            path = self.job / f"student/{student}.java"
            text = path.read_text()
            text = (
                text.replace(
                    "publisher = value;", 'this.publisher = "Неверное издательство";'
                )
                if student == "Book"
                else text.replace(
                    "values.length - 1; i >= 0; i--", "0; i < values.length; i++"
                )
            )
            self.assertNotEqual(
                text, path.read_text(), "Fault control must modify the submitted source"
            )
            path.write_text(text)
        result = self.run_job()
        assert "score" in result
        native = feedback(result, self.cfg)
        destination = os.environ.get("C3_PRODUCT_RECEIPTS")
        if destination:
            out = Path(destination)
            out.mkdir(parents=True, exist_ok=True)
            (out / (self._testMethodName + ".json")).write_text(
                json.dumps(
                    {
                        "sourceInputs": copied,
                        "submittedSha256": hashlib.sha256(
                            (self.job / f"student/{student}.java").read_bytes()
                        ).hexdigest(),
                        "result": result,
                        "native": native,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        assert "apiPrecheck" in result
        self.assertEqual(result["apiPrecheck"], "success")
        return result, native

    def test_actual_book_23_leaves_and_all_state_components(self) -> None:
        result, native = self.early_job("objects/book-selection", "Book")
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (23, 23)
        )
        checks = [c for case in result_counts(result)["cases"] for c in case_checks(case)]
        states = [
            c
            for case in result_counts(result)["cases"]
            if case["name"] == "Полная книга с несколькими авторами"
            for c in case_checks(case)
        ]
        self.assertTrue(states)
        for component in (
            "id=17",
            "title=",
            "authors=",
            "publisher=",
            "year=2024",
            "pages=312",
            "price=19.75",
            "binding=",
        ):
            self.assertIn(component, states[0]["expected"])
        self.assertTrue(any("[{id=" in c["expected"] for c in checks))
        self.assertEqual(public_score(native), 1)
        self.assertEqual(completeness(native), "complete")

    def test_actual_book_wrong_publisher_is_observed(self) -> None:
        result, native = self.early_job("objects/book-selection", "Book", faulty=True)
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (23, 22)
        )
        case = next(c for c in result_counts(result)["cases"] if c["status"] == "failed")
        self.assertIn('publisher="Мир"', case_checks(case)[0]["expected"])
        self.assertIn('publisher="Неверное издательство"', case_checks(case)[0]["actual"])
        self.assertEqual(public_score(native), 22 / 23)
        self.assertEqual(len(public_tests(native)), 23)

    def test_actual_reverse_private_helper(self) -> None:
        result, native = self.early_job("arrays/reverse-array", "Main")
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (4, 4)
        )
        self.assertTrue(
            any(
                c["property"] == "равенство массивов" and c["expected"] == c["actual"]
                for case in result_counts(result)["cases"]
                for c in case_checks(case)
            )
        )
        self.assertEqual(public_score(native), 1)
        self.assertEqual(completeness(native), "complete")

    def test_actual_reverse_wrong_order(self) -> None:
        result, native = self.early_job("arrays/reverse-array", "Main", faulty=True)
        assert "score" in result
        self.assertEqual(
            (result_counts(result)["executed"], result_counts(result)["passed"]), (4, 2)
        )
        self.assertEqual(public_score(native), 0.5)
        self.assertTrue(
            any(
                c.get("differenceIndex") == "0"
                for case in result_counts(result)["cases"]
                for c in case_checks(case)
            )
        )


class CheckShape(unittest.TestCase):
    def counts(self) -> JUnitCounts:
        return {
            "discovered": 1,
            "executed": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "aborted": 0,
            "containerFailures": 0,
            "eventErrors": 0,
            "complete": True,
            "registered": ["T#t"],
            "started": ["T#t"],
            "outcomes": {"T#t": "successful"},
            "failureKinds": {},
            "feedbackProtocolVersion": 2,
            "cases": [
                {
                    "id": "T#t",
                    "name": "Проверка",
                    "status": "passed",
                    "checks": [
                        {
                            "site": "T.java:1:1",
                            "property": "равенство",
                            "availability": "complete",
                            "expected": "1",
                            "actual": "1",
                            "delegated": "returned",
                        }
                    ],
                }
            ],
        }

    def test_validated_checks_have_exact_bounded_public_shape(self) -> None:
        counts = self.counts()
        validate_counts(counts)
        mutations: list[tuple[str, object]] = [
            ("grant", {}),
            ("_bci", "42"),
            ("site", "/host/T.java:1:1"),
            ("actual", "x" * 8193),
            ("delegated", "invented"),
        ]
        for field, value in mutations:
            bad = copy.deepcopy(counts)
            bad_check: object = case_checks(bad["cases"][0])[0]
            assert is_object(bad_check)
            bad_check[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_counts(bad)


if __name__ == "__main__":
    unittest.main()
