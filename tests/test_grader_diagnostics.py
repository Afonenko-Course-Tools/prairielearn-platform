"""Первичная диагностика незавершённого JUnit и граница частного отчёта."""

from platform_modules import grader_hook

from pathlib import Path
import selectors
import signal
import sys
import unittest
from unittest.mock import patch

from collections.abc import Mapping, Sequence
from typing import Literal, NoReturn, Protocol, runtime_checkable
from grading_types import JavaGradingDescriptor, JavaOutcome
import test_grading_job as fixtures

grader = fixtures.grader


@runtime_checkable
class ProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout: float,
        output_limit: int = 65536,
        *,
        diagnostics: dict[str, str],
        stage: str,
    ) -> tuple[int, str, Literal["timeout", "output_limit"] | None]: ...


@runtime_checkable
class ErrorObservation(Protocol):
    @property
    def outcome(self) -> JavaOutcome | None: ...


@runtime_checkable
class ReportHelpers(Protocol):
    def __call__(self) -> Mapping[str, object]: ...


def process_runner() -> ProcessRunner:
    run: object = grader_hook(grader, "_run")
    assert isinstance(run, ProcessRunner)
    return run


def error_outcome(error: Exception) -> JavaOutcome:
    assert isinstance(error, ErrorObservation) and error.outcome is not None
    return error.outcome


class ProcessDiagnostics(unittest.TestCase):
    def test_split_streams_and_nonzero_exit(self) -> None:
        diagnostics: dict[str, str] = {}
        code, output, reason = process_runner()(
            [
                sys.executable,
                "-c",
                'import sys; print("out"); print("err",file=sys.stderr); sys.exit(23)',
            ],
            Path("/tmp"),
            3,
            100,
            diagnostics=diagnostics,
            stage="execution",
        )
        self.assertEqual((code, reason), (23, None))
        self.assertIn("out", output)
        self.assertIn("err", output)
        self.assertEqual(diagnostics["execution.stdout"], "out\n")
        self.assertEqual(diagnostics["execution.stderr"], "err\n")
        self.assertEqual(diagnostics["execution.exitCode"], "23")
        self.assertEqual(diagnostics["stage"], "execution")

    def test_total_stream_bound_and_timeout_are_distinct(self) -> None:
        for script, maximum, expected in (
            (
                'import sys; print("x"*10000); print("y"*10000,file=sys.stderr)',
                128,
                "output_limit",
            ),
            (
                'import os; os.write(1,b"\\xff"*10000);os.write(2,b"\\xff"*10000)',
                128,
                "output_limit",
            ),
            (
                'import sys,time; print("started",flush=True); time.sleep(10)',
                1024,
                "timeout",
            ),
        ):
            with self.subTest(termination=expected):
                diagnostics: dict[str, str] = {}
                _, output, reason = process_runner()(
                    [sys.executable, "-c", script],
                    Path("/tmp"),
                    0.2,
                    maximum,
                    diagnostics=diagnostics,
                    stage="execution",
                )
                self.assertEqual(reason, expected)
                self.assertLessEqual(len(output.encode()), maximum)
                self.assertLessEqual(
                    sum(
                        len(diagnostics["execution." + name].encode())
                        for name in ("stdout", "stderr")
                    ),
                    maximum,
                )
                self.assertEqual(diagnostics["execution.termination"], expected)

    def test_operator_interruption_is_preserved_and_child_is_stopped(self) -> None:
        diagnostics: dict[str, str] = {}
        with patch.object(
            selectors.DefaultSelector, "select", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                process_runner()(
                    [sys.executable, "-c", "import time;time.sleep(10)"],
                    Path("/tmp"),
                    3,
                    diagnostics=diagnostics,
                    stage="execution",
                )
        self.assertEqual(diagnostics["execution.termination"], "interrupted")
        self.assertEqual(diagnostics["execution.exitCode"], str(-signal.SIGKILL))

    def test_signal_and_unavailable_tool_keep_primary_cause(self) -> None:
        diagnostics: dict[str, str] = {}
        code, _, _ = process_runner()(
            [
                sys.executable,
                "-c",
                "import os,signal;os.kill(os.getpid(),signal.SIGTERM)",
            ],
            Path("/tmp"),
            3,
            diagnostics=diagnostics,
            stage="execution",
        )
        self.assertEqual(code, -signal.SIGTERM)
        self.assertEqual(diagnostics["execution.termination"], "signal")
        with self.assertRaises(grader.GraderError):
            process_runner()(
                ["/missing-fictional-tool"],
                Path("/tmp"),
                3,
                diagnostics=diagnostics,
                stage="runnerCompilation",
            )
        self.assertEqual(diagnostics["stage"], "runnerCompilation")
        self.assertEqual(diagnostics["runnerCompilation.termination"], "spawn-error")
        self.assertIn("missing-fictional-tool", diagnostics["runnerCompilation.stderr"])


class JUnitDiagnostics(unittest.TestCase):
    job: Path
    cfg: JavaGradingDescriptor
    setUp = fixtures.JUnitJob.setUp
    run_job = fixtures.JUnitJob.run_job

    def test_missing_report_preserves_completed_stages_and_both_streams(self) -> None:
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){System.out.println("before exit");System.err.println("last error");System.exit(23);return 42;}}'
        )
        with self.assertRaises(grader.GraderError) as caught:
            self.run_job()
        result = error_outcome(caught.exception)
        self.assertEqual(result.get("studentCompilation"), "success")
        self.assertEqual(result.get("trustedCompilation"), "success")
        self.assertNotIn("score", result)
        assert "diagnostics" in result
        diagnostics = result["diagnostics"]
        self.assertEqual(diagnostics["stage"], "execution")
        self.assertEqual(diagnostics["execution.exitCode"], "23")
        self.assertIn("before exit", diagnostics["execution.stdout"])
        self.assertIn("last error", diagnostics["execution.stderr"])

    def test_timeout_keeps_observations_without_score(self) -> None:
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){System.out.println("before loop");while(true){}}}'
        )
        self.cfg["limits"]["run-seconds"] = 0.5
        result = self.run_job()
        self.assertEqual(result["classification"], "infrastructure-failure")
        self.assertEqual(result.get("trustedCompilation"), "success")
        assert "diagnostics" in result
        self.assertEqual(result["diagnostics"]["execution.termination"], "timeout")
        self.assertIn("before loop", result.get("output", ""))
        self.assertNotIn("score", result)

    def test_bad_report_keeps_completed_execution(self) -> None:
        original: object = grader_hook(grader, "_junit_result_helpers")
        assert isinstance(original, ReportHelpers)
        helpers = original()

        def invalid_report(path: str | Path) -> NoReturn:
            raise ValueError("fictional damaged report")

        with patch.object(
            grader,
            "_junit_result_helpers",
            return_value={**helpers, "read_junit_report": invalid_report},
        ):
            with self.assertRaises(grader.GraderError) as caught:
                self.run_job()
        result = error_outcome(caught.exception)
        self.assertEqual(result.get("trustedCompilation"), "success")
        assert "diagnostics" in result
        self.assertEqual(result["diagnostics"]["execution.exitCode"], "0")
        self.assertIn("fictional damaged report", result.get("message", ""))
        self.assertNotIn("score", result)
