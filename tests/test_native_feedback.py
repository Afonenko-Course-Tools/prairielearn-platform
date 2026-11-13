"""Сводный результат student-tests сохраняет исходную политику мутантов."""

import runpy
import unittest
from pathlib import Path
from selected_job_fixture import fixture_set_up, fixture_run_job
import test_grading_job as fixtures

boundary = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "runtime/student_feedback.py")
)["student_result"]


class NativeFeedbackTests(unittest.TestCase):
    setUp = fixture_set_up(fixtures.MutationJob.setUp)
    run_job = fixture_run_job(fixtures.MutationJob.run_job)
    setup_mutation = fixtures.MutationJob.setup_mutation

    def test_mutation_success_preserves_score(self):
        self.setup_mutation()
        result = self.run_job()
        native = boundary(result, self.cfg)
        self.assertEqual(native["score"], 1)
        self.assertNotIn("variants", native)
