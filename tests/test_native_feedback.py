"""Private verification observations and the separate native student boundary."""

from __future__ import annotations

from types import FunctionType
from typing import Protocol, runtime_checkable
from selected_job_fixture import fixture_set_up, fixture_run_job, fixture_record, fixture_list, fixture_text

import json
import os
from pathlib import Path
import unittest
import test_grading_job as fixtures
import runpy

@runtime_checkable
class _StudentResult(Protocol):
    def __call__(self, result: object, descriptor: object) -> object: ...


class _MutationOwner(Protocol):
    @property
    def job(self) -> Path: ...
    @property
    def cfg(self) -> dict[str, object]: ...


@runtime_checkable
class _MutationSetup(Protocol):
    def __call__(self, owner: _MutationOwner, /) -> None: ...


def _student_boundary(value: object) -> _StudentResult:
    if not isinstance(value, _StudentResult):
        raise AssertionError("Функция student_result недоступна")
    return value


boundary = _student_boundary(runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "runtime/student_feedback.py")
)["student_result"])

def _mutation_setup(value: object) -> _MutationSetup:
    if not isinstance(value, _MutationSetup) or not isinstance(value, FunctionType):
        raise AssertionError("Fixture mutation setup должен быть прежней unbound функцией")
    return value


mutation_setup = _mutation_setup(getattr(fixtures.MutationJob, "setup_mutation"))


def _boundary(result: object, descriptor: object) -> dict[str, object]:
    return fixture_record(boundary(result, descriptor))



class NativeFeedbackTests(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    setUp = fixture_set_up(fixtures.JUnitJob.setUp)
    run_job = fixture_run_job(fixtures.JUnitJob.run_job)

    def result(self, name: str, source: str) -> dict[str, object]:
        (self.job / "student/Student.java").write_text(source)
        result = self.run_job()
        self.capture(name, result)
        return result

    def capture(self, name: str, result: object) -> None:
        native = _boundary(result, self.cfg)
        self.assertIn("feedback", native)
        self.assertNotIn("rawResult", native)
        self.assertNotIn("variants", native)
        self.assertNotIn("output", native)
        if os.environ.get("PL_FEEDBACK_CAPTURE_DIR"):
            output = Path(os.environ["PL_FEEDBACK_CAPTURE_DIR"])
            output.mkdir(parents=True, exist_ok=True)
            (output / (name + ".json")).write_text(
                json.dumps(native, indent=2, ensure_ascii=False) + "\n"
            )

    def test_missing_api_has_native_test_message(self) -> None:
        r = self.result("missing-api", "public class Student {}")
        self.assertEqual(r["classification"], "behavior-failure")
        self.assertEqual(r["score"], 0)
        self.assertEqual(fixture_record(r["counts"])["failed"], 1)
        self.assertEqual(fixture_record(r["counts"])["executed"], 1)
        self.assertEqual(
            len(fixture_list(r.get("tests", []))), 1, "Native UI requires tests at the result root"
        )
        self.assertEqual(fixture_record(fixture_list(fixture_record(r["rawResult"])["tests"])[0])["message"], "")
        self.assertEqual(fixture_record(fixture_list(r["tests"])[0])["points"], 0)
        self.assertEqual(fixture_record(fixture_list(r["tests"])[0])["max_points"], 1)
        native = _boundary(r, self.cfg)
        self.assertEqual(fixture_record(native["feedback"])["cases"], [
            {"name": "right()", "status": "failed", "checks": []}
        ])
        self.assertEqual(fixture_record(native["feedback"])["feedbackCompleteness"], "incomplete")
        self.assertEqual(len(fixture_list(native["tests"])), 1)
        leaf = fixture_record(fixture_list(native["tests"])[0])
        self.assertEqual((leaf["name"], leaf["points"], leaf["max_points"]), ("right()", 0, 1))
        self.assertIn("Подробности сравнения не получены:", fixture_text(leaf["message"]))
        self.assertNotIn("answer", fixture_text(leaf["message"]))
        self.assertNotIn("NoSuchMethodException", fixture_text(leaf["message"]))

    def test_whole_executor_timeout_is_infrastructure_without_fake_cases(self) -> None:
        result = self.result(
            "timeout",
            "public class Student {public static int answer(){while(true){}}}",
        )
        self.assertEqual(result["classification"], "infrastructure-failure")
        self.assertIs(result["timed_out"], True)
        native = _boundary(result, self.cfg)
        self.assertEqual(native["classification"], "infrastructure-failure")
        self.assertEqual(fixture_record(native["feedback"])["kind"], "infrastructure")
        self.assertIn("3 с", fixture_text(native["message"]))
        for value in (result, native):
            self.assertFalse(value["gradable"])
            self.assertTrue(value["grading_error"])
            for field in ("score", "counts", "tests", "rawResult"):
                self.assertNotIn(field, value)
        self.assertNotIn("cases", fixture_record(native["feedback"]))
        self.assertNotIn("feedbackCompleteness", fixture_record(native["feedback"]))

    def test_whole_executor_output_stop_is_infrastructure_without_fake_cases(self) -> None:
        with self.assertRaises(fixtures.grader.GraderError):
            self.result(
                "overflow",
                'public class Student {public static int answer(){while(true){System.out.print("x".repeat(8192));}}}',
            )

    def test_mutation_success_explains_expected_rejections(self) -> None:
        mutation_setup(self)
        r = self.run_job()
        self.capture("mutation-success", r)
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["classification"], "success")
        self.assertEqual(fixture_record(fixture_record(fixture_record(r["variants"])["correct"])["counts"])["passed"], 1)
        self.assertEqual(fixture_record(fixture_record(fixture_record(r["variants"])["wrong"])["counts"])["failed"], 1)
        self.assertIn("Correct implementations accepted: 1/1", fixture_text(r.get("message", "")))
        self.assertIn("mutants rejected: 1/1", fixture_text(r["message"]))
        self.assertNotIn("tests", r)

    def test_mutation_noop_explains_missing_rejections(self) -> None:
        mutation_setup(self)
        (self.job / "student/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.Test; public class AnswerTest { @Test void noop(){} }"
        )
        r = self.run_job()
        self.capture("mutation-noop", r)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["classification"], "behavior-failure")
        self.assertEqual(fixture_record(fixture_record(fixture_record(r["variants"])["wrong"])["counts"])["failed"], 0)
        self.assertIn("Correct implementations accepted: 1/1", fixture_text(r.get("message", "")))
        self.assertIn("mutants rejected: 0/1", fixture_text(r["message"]))
        self.assertNotIn("tests", r)

    def test_mutation_disabled_reports_quality_failure(self) -> None:
        mutation_setup(self)
        (self.job / "student/AnswerTest.java").write_text(
            fixtures.TEST.replace("@Test", "@org.junit.jupiter.api.Disabled @Test")
        )
        r = self.run_job()
        self.capture("mutation-quality", r)
        self.assertEqual(r["classification"], "student-test-quality-failure")
        self.assertEqual(r["score"], 0)
        self.assertIn("quality", fixture_text(r.get("message", "")).lower())
        self.assertNotIn(str(self.job), fixture_text(r["message"]))
