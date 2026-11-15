"""Entrypoint contract accepts only explicit JUnit jobs on Java25."""

import json
import sys
from pathlib import Path
import subprocess
import unittest
import test_grading_job as fixtures
from gradle_unit_fixtures import unit_platform
from selected_job_fixture import fixture_set_up, fixture_run_job, fixture_record

grader = fixtures.grader
ROOT = fixtures.ROOT


class EntrypointTests(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    setUp = fixture_set_up(fixtures.JUnitJob.setUp)
    run_job = fixture_run_job(fixtures.JUnitJob.run_job)

    def test_source_traversal_is_configuration_error(self) -> None:
        self.cfg["sourceFiles"] = ["../tests/AnswerTest.java"]
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_legacy_course_main_descriptor_is_rejected(self) -> None:
        self.cfg["mainClass"] = "Checks"
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_symlink_submission_is_not_gradable(self) -> None:
        p = self.job / "student/Student.java"
        p.unlink()
        p.symlink_to("/etc/hosts")
        self.assertFalse(self.run_job()["gradable"])

    def test_cli_writes_standard_pl_results(self) -> None:
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        p = subprocess.run(
            [
                sys.executable,
                str(unit_platform(self) / "images/java25-grader/grade.py"),
                "--job-dir",
                str(self.job),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        r = fixture_record(json.loads((self.job / "results/results.json").read_text()))
        self.assertEqual(r["score"], 1)

    def test_cli_infrastructure_failure_has_no_score(self) -> None:
        (self.job / "tests/AnswerTest.java").unlink()
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        p = subprocess.run(
            [
                sys.executable,
                str(unit_platform(self) / "images/java25-grader/grade.py"),
                "--job-dir",
                str(self.job),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0)
        r = fixture_record(json.loads((self.job / "results/results.json").read_text()))
        self.assertTrue(r["grading_error"])
        self.assertNotIn("score", r)
