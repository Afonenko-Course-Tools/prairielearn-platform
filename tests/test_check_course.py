"""CLI проверяет реальные Native controls и сообщает факты исполнения без receipt."""

import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from typing import Protocol, runtime_checkable
from unittest.mock import patch
import test_delivery5 as fixtures
from test_selected_file_delivery import manifest as selected_manifest

ROOT = Path(__file__).resolve().parents[1]


class CheckCourse(unittest.TestCase):
    manifest: dict[str, object]

    def setUp(self) -> None:
        self.fixture = fixtures.Delivery5()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.manifest = {
            "schemaVersion": 3,
            "courseId": "demo",
            "bookRoot": "tasks",
            "projects": [],
        }

    def run_check(
        self, *args: str
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        manifest = self.root / "private-checks.json"
        manifest.write_text(json.dumps(self.manifest))
        delivery = self.root / "delivery.json"
        delivery.write_text(json.dumps(self.fixture.d))
        output = self.root / "report.json"
        run = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/check-course.py"),
                "verify",
                "--manifest",
                str(manifest),
                "--scope",
                "delivery",
                "--delivery",
                str(delivery),
                "--output",
                str(output),
                *args,
            ],
            capture_output=True,
            text=True,
        )
        return run, fixtures.record(json.loads(output.read_text()))

    def test_manual_package_reports_controls_without_automatic_job_score_or_receipt(
        self,
    ) -> None:
        run, report = self.run_check()
        self.assertEqual(run.returncode, 0, report)
        self.assertEqual(
            fixtures.record(report["automatic"])["state"], "not-applicable"
        )
        self.assertEqual(report["results"], [])
        self.assertNotIn("receipt", report)
        self.assertNotIn("Hash", json.dumps(report))
        self.assertEqual(
            fixtures.record(report["packageIntegrity"])["status"], "success"
        )
        self.assertEqual(
            fixtures.record(report["automatic"])["reason"], "no-project-automatic"
        )

    def test_unknown_native_question_is_tool_failure(self) -> None:
        run, report = self.run_check("--id", "demo/exr-unknown")
        self.assertEqual(run.returncode, 2)
        self.assertEqual(report["classification"], "infrastructure-failure")

    def test_selected_manual_scenario_is_partial_diagnostic(self) -> None:
        run, report = self.run_check("--scenario", "starter")
        self.assertEqual(run.returncode, 1)
        self.assertEqual(report["coverage"], "partial")
        self.assertNotIn("receipt", report)

    def test_unsafe_native_controls_never_become_zero_score(self) -> None:
        self.fixture.put(
            "questions/" + self.fixture.q + "/question.html", "<p>Нет ввода</p>"
        )
        run, report = self.run_check()
        self.assertEqual(run.returncode, 2)
        self.assertNotIn("score", report)


@runtime_checkable
class Checker(Protocol):
    def main(self) -> int: ...


class EmptyDeclaredChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(
            self.enterContext(tempfile.TemporaryDirectory(prefix="empty-declared-"))
        )
        self.source = self.root / "checks.json"
        self.output = self.root / "report.json"
        self.manifest: dict[str, object] = {
            "schemaVersion": 3,
            "courseId": "fictional",
            "bookRoot": "tasks",
            "projects": [],
        }

    def run_cli(self, *flags: str) -> tuple[int, dict[str, object]]:
        self.source.write_text(json.dumps(self.manifest))
        spec = importlib.util.spec_from_file_location(
            "empty_declared_cli", ROOT / "tools/check-course.py"
        )
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        assert isinstance(cli, Checker)
        argv = [
            "check-course.py",
            "verify",
            "--manifest",
            str(self.source),
            "--scope",
            "declared",
            "--backend",
            "container",
            "--output",
            str(self.output),
            *flags,
        ]
        # Настоящие parser/inventory/JSON Schema; для пустого набора недопустимы
        # даже подготовка grader job и вычисление фиктивного grading summary.
        with (
            patch.object(sys, "argv", argv),
            patch.object(cli, "prepare_job") as prepare,
            patch.object(cli, "run_job") as backend,
            patch.object(cli, "verify_results") as verify,
        ):
            code = cli.main()
            prepare.assert_not_called()
            backend.assert_not_called()
            verify.assert_not_called()
        return code, fixtures.record(json.loads(self.output.read_text()))

    def test_full_empty_declared_is_not_applicable_without_delivery(self) -> None:
        code, report = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(
            report["automatic"],
            {"state": "not-applicable", "reason": "no-declared-checks"},
        )
        for key in ("inventory", "results", "remaining", "unavailable"):
            self.assertEqual(report[key], [])
        for key in ("coverage", "summary", "score", "packageIntegrity"):
            self.assertNotIn(key, report)
        # Проверяется также настоящий process exit штатного публичного CLI.
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/check-course.py"),
                "verify",
                "--manifest",
                str(self.source),
                "--scope",
                "declared",
                "--backend",
                "container",
                "--output",
                str(self.root / "process-report.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads((self.root / "process-report.json").read_text()), report
        )

    def test_filtered_empty_selection_is_not_success(self) -> None:
        for flags in (
            ("--scenario", "starter"),
            ("--ready-only",),
            ("--ready-only", "--scenario", "starter"),
        ):
            with self.subTest(flags=flags):
                code, report = self.run_cli(*flags)
                self.assertEqual(code, 1)
                self.assertEqual(report["coverage"], "partial")
                self.assertEqual(
                    report["automatic"],
                    {"state": "not-verified", "reason": "partial-selection"},
                )
                self.assertNotIn("summary", report)
                self.assertNotIn("score", report)
        code, report = self.run_cli("--id", "fictional/exr-unknown")
        self.assertEqual(code, 2)
        self.assertEqual(report["classification"], "infrastructure-failure")
        self.assertNotIn("automatic", report)

    def test_ready_filter_cannot_turn_declared_projects_into_not_applicable(
        self,
    ) -> None:
        value = selected_manifest()
        value["projects"][0]["readiness"] = {"ready": False, "missing": ["tests"]}
        self.manifest = dict(value)
        code, report = self.run_cli("--ready-only")
        self.assertEqual(code, 1)
        self.assertEqual(report["coverage"], "partial")
        self.assertEqual(
            report["automatic"],
            {"state": "not-verified", "reason": "partial-selection"},
        )

    def test_invalid_empty_manifest_is_still_rejected_by_real_schema(self) -> None:
        invalid: list[dict[str, object]] = [
            {"schemaVersion": 3, "courseId": "fictional", "bookRoot": "tasks"},
            {
                "schemaVersion": 3,
                "courseId": "fictional",
                "bookRoot": "tasks",
                "projects": {},
            },
            {
                "schemaVersion": 2,
                "courseId": "fictional",
                "bookRoot": "tasks",
                "projects": [],
            },
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.manifest = value
                code, report = self.run_cli()
                self.assertEqual(code, 2)
                self.assertEqual(report["classification"], "infrastructure-failure")
                self.assertNotIn("automatic", report)


if __name__ == "__main__":
    unittest.main()
