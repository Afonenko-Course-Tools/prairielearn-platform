"""C3-1: настоящий production путь assertion → counts → native feedback."""

import copy
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import runpy
import unittest
import test_grading_job as fixtures

helpers = runpy.run_path(str(fixtures.ROOT / "runtime/junit_result.py"))
feedback = runpy.run_path(str(fixtures.ROOT / "runtime/student_feedback.py"))[
    "student_result"
]


class ProductionCase(unittest.TestCase):
    def run_job(self):
        result = fixtures.JUnitJob.run_job(self)
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

    def preserve(self, path):
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

    def setUp(self):
        fixtures.JUnitJob.setUp(self)
        self.calls = []
        original = fixtures.grader._run

        def measured(command, *args, **kwargs):
            started = time.monotonic()
            before = {}
            if "Transform" in command:
                path = Path(command[command.index("Transform") + 1])
                if path.is_dir():
                    before = {
                        str(p.relative_to(path)): self.preserve(p)
                        for p in path.rglob("*.class")
                    }
            sealed = {}
            params = None
            reports = {}
            jars = {}
            if "PlatformJUnitAdapter" in command and "--module-path" in command:
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
            result = original(command, *args, **kwargs)
            if params is not None:
                reports = {
                    p.name: self.preserve(p)
                    for p in parameter_file.parent.parent.joinpath("results").glob(
                        "*.json"
                    )
                }

            after = {}
            if before:
                after = {
                    str(p.relative_to(path)): self.preserve(p)
                    for p in path.rglob("*.class")
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

    def save_execution(self):
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

    def test_real_arguments_reach_native_without_new_points(self):
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
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (1, 0)
        )
        checks = result["counts"]["cases"][0].get("checks", [])
        self.assertEqual(
            [(c["expected"], c["actual"]) for c in checks], [("42", "42"), ("41", "42")]
        )
        native = feedback(result, self.cfg)
        self.assertEqual(native["score"], 0)
        self.assertEqual(len(native["tests"]), 1)
        case = native["feedback"]["cases"][0]
        self.assertEqual(
            case["reporter"],
            {
                "origin": "trusted-TestReporter",
                "expected": "Отдельное ожидание",
                "actual": "Отдельное наблюдение",
            },
        )
        self.assertIn("Ожидается: 41", native["tests"][0]["description"])
        self.assertNotIn("PRIVATE_ASSERTION_MESSAGE", str(native))

    def test_string_difference_beyond_10240_lines_is_localized(self):
        (self.job / "student/Student.java").write_text(
            'public class Student {public static String answer(){return "строка\\n".repeat(12000)+"Б";}}'
        )
        (self.job / "tests/AnswerTest.java").write_text(
            'import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test @DisplayName("Длинная строка") void result(){assertEquals("строка\\n".repeat(12000)+"А",Student.answer());}}'
        )
        result = self.run_job()
        checks = result["counts"]["cases"][0].get("checks", [])
        self.assertEqual(len(checks), 1)
        check = checks[0]
        self.assertEqual(
            (
                check["differenceIndex"],
                check["differenceLine"],
                check["differenceColumn"],
            ),
            ("84000", "12001", "1"),
        )
        self.assertIn("А", check["differenceExpected"])
        self.assertIn("Б", check["differenceActual"])
        self.assertLess(len(str(feedback(result, self.cfg))), 40000)

    def test_measured_byte_difference_after_10240(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {@Test @DisplayName("Дальнее различие байтов") void result(){
 byte[] expected=new byte[12000],actual=expected.clone();actual[11017]=42;
 assertArrayEquals(expected,actual);
}}""")
        result = self.run_job()
        check = result["counts"]["cases"][0]["checks"][0]
        self.assertEqual(check["differenceIndex"], "11017")
        self.assertEqual(
            (check["differenceExpected"], check["differenceActual"]), ("00", "2a")
        )
        self.assertEqual(feedback(result, self.cfg)["score"], 0)
        self.assertEqual(result["counts"]["executed"], 1)

    def test_callback_supplier_timeout_and_opaque_delegate_once(self):
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
        self.assertEqual(result["score"], 1)
        checks = result["counts"]["cases"][0]["checks"]
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
        self.assertEqual(native["feedback"]["feedbackCompleteness"], "incomplete")
        for text in ("PRIVATE_OPAQUE_TEXT", "PRIVATE_LAZY_MESSAGE"):
            self.assertNotIn(text, str(native))

    def test_no_argument_fail_preserves_one_native_leaf(self):
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void result(){fail();}}"
        )
        result = self.run_job()
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["failed"]), (1, 1)
        )
        self.assertEqual(feedback(result, self.cfg)["score"], 0)

    def test_overflow_preserves_delegate_score_and_marks_incomplete(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test void checks(){for(int i=0;i<100;i++)assertEquals(i,i);}
 @Test void snapshots(){byte[] bytes=new byte[40000];assertArrayEquals(bytes,bytes.clone());}
 @Test void stringScan(){assertEquals("x".repeat(1100000),"x".repeat(1100000));}
}""")
        result = self.run_job()
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (3, 3)
        )
        self.assertEqual(result["score"], 1)
        cases = result["counts"]["cases"]
        check_quota = next(c for c in cases if "checks()" in c["id"])
        self.assertEqual(len(check_quota["checks"]), 64)
        self.assertEqual(
            check_quota["checks"][-1]["availability"], "incomplete: check quota"
        )
        scan = next(c for c in cases if "stringScan()" in c["id"])["checks"][0]
        self.assertEqual(
            scan["availability"], "incomplete: string difference scan quota"
        )
        self.assertNotIn("differenceIndex", scan)
        self.assertEqual(
            feedback(result, self.cfg)["feedback"]["feedbackCompleteness"], "incomplete"
        )

    def test_student_helper_reentry_has_no_observation_authority(self):
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){try{Class.forName("AnswerTest").getMethod("helper").invoke(null);}catch(Exception error){throw new RuntimeException(error);}return 42;}}'
        )
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {public static void helper(){assertEquals(7,7);}@Test void result(){assertEquals(42,Student.answer());}}"
        )
        result = self.run_job()
        self.assertEqual(result["score"], 1)
        checks = result["counts"]["cases"][0]["checks"]
        self.assertEqual([(c["expected"], c["actual"]) for c in checks], [("42", "42")])

    def test_late_preemptive_worker_cannot_change_published_leaf(self):
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;import java.time.Duration;
public class AnswerTest {
 @Test @DisplayName("Истёкший leaf") void late(){assertTimeoutPreemptively(Duration.ofMillis(20),()->{
   long until=System.nanoTime()+150_000_000L;while(System.nanoTime()<until)Thread.onSpinWait();assertEquals(7,7);
 });}
 @Test @DisplayName("Следующий leaf") void next() throws Exception {Thread.sleep(200);assertEquals(42,Student.answer());}
}""")
        result = self.run_job()
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (2, 1)
        )
        cases = result["counts"]["cases"]
        self.assertFalse(
            any(c["expected"] == "7" for case in cases for c in case["checks"])
        )
        native = feedback(result, self.cfg)
        self.assertEqual(native["score"], 0.5)
        self.assertEqual(len(native["tests"]), 2)


class ActualEarlyFeedback(ProductionCase):

    def early_job(self, project, student, faulty=False):
        source = os.environ.get("JAVA_EARLY_PROJECTS")
        if not source:
            self.skipTest("JAVA_EARLY_PROJECTS задаёт принятый D1 source")
        source = Path(source)
        unit = source / "projects" / project
        for path in (self.job / "student").glob("*.java"):
            path.unlink()
        for path in (self.job / "tests").glob("*.java"):
            path.unlink()
        copied = {}

        def put(path, target):
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
        self.assertEqual(result["apiPrecheck"], "success")
        return result, native

    def test_actual_book_23_leaves_and_all_state_components(self):
        result, native = self.early_job("objects/book-selection", "Book")
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (23, 23)
        )
        checks = [c for case in result["counts"]["cases"] for c in case["checks"]]
        states = [
            c
            for case in result["counts"]["cases"]
            if case["name"] == "Полная книга с несколькими авторами"
            for c in case["checks"]
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
        self.assertEqual(native["score"], 1)
        self.assertEqual(native["feedback"]["feedbackCompleteness"], "complete")

    def test_actual_book_wrong_publisher_is_observed(self):
        result, native = self.early_job("objects/book-selection", "Book", faulty=True)
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (23, 22)
        )
        case = next(c for c in result["counts"]["cases"] if c["status"] == "failed")
        self.assertIn('publisher="Мир"', case["checks"][0]["expected"])
        self.assertIn('publisher="Неверное издательство"', case["checks"][0]["actual"])
        self.assertEqual(native["score"], 22 / 23)
        self.assertEqual(len(native["tests"]), 23)

    def test_actual_reverse_private_helper(self):
        result, native = self.early_job("arrays/reverse-array", "Main")
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (4, 4)
        )
        self.assertTrue(
            any(
                c["property"] == "равенство массивов" and c["expected"] == c["actual"]
                for case in result["counts"]["cases"]
                for c in case["checks"]
            )
        )
        self.assertEqual(native["score"], 1)
        self.assertEqual(native["feedback"]["feedbackCompleteness"], "complete")

    def test_actual_reverse_wrong_order(self):
        result, native = self.early_job("arrays/reverse-array", "Main", faulty=True)
        self.assertEqual(
            (result["counts"]["executed"], result["counts"]["passed"]), (4, 2)
        )
        self.assertEqual(native["score"], 0.5)
        self.assertTrue(
            any(
                c.get("differenceIndex") == "0"
                for case in result["counts"]["cases"]
                for c in case["checks"]
            )
        )


class CheckShape(unittest.TestCase):
    def counts(self):
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

    def test_validated_checks_have_exact_bounded_public_shape(self):
        counts = self.counts()
        helpers["validate_counts"](counts)
        for field, value in [
            ("grant", {}),
            ("_bci", "42"),
            ("site", "/host/T.java:1:1"),
            ("actual", "x" * 8193),
            ("delegated", "invented"),
        ]:
            bad = copy.deepcopy(counts)
            bad["cases"][0]["checks"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                helpers["validate_counts"](bad)


if __name__ == "__main__":
    unittest.main()
