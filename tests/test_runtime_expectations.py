"""Ожидаемая ошибка исполнения заготовки проходит штатную подготовку Job."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import test_selected_file_delivery as fixtures
from selected_job_fixture import fixture_record

g = fixtures.g


class RuntimeExpectations(unittest.TestCase):
    def test_runtime_failure_contract_reaches_prepared_job(self) -> None:
        manifest = fixtures.manifest()
        project = manifest["projects"][0]
        project["check"]["contract-cases"] = "cases.json"
        project["contractCases"] = fixtures.row(
            "cases.json",
            json.dumps(
                {
                    "schemaVersion": 1,
                    "cases": [
                        {
                            "id": "runtime",
                            "sources": [
                                {
                                    "fixture": "tests/fixtures/runtime.java",
                                    "submission": "Answer.java",
                                }
                            ],
                            "expected": {
                                "classification": "student-runtime-failure",
                                "score": {"exactly": 0},
                            },
                        }
                    ],
                }
            ).encode(),
            "tests/cases.json",
        )
        project["contractFixtures"] = [
            fixtures.row(
                "Answer.java",
                b"public class Answer { static int value() { throw new IllegalStateException(); } }",
                "tests/fixtures/runtime.java",
            )
        ]
        with tempfile.TemporaryDirectory() as snapshot:
            try:
                scenarios = g.scenario_inventory(manifest, Path(snapshot))
            except g.JobError:
                self.fail(
                    "Контрактная схема отвергла существующую классификацию student-runtime-failure"
                )
            self.assertEqual(
                [entry["scenario"] for entry in scenarios],
                ["contract:runtime", "starter"],
            )
            job = g.prepare_job(
                manifest,
                Path(snapshot),
                "demo/exr-answer",
                "contract:runtime",
                registry=fixtures.registry(),
            )
            try:
                expectations = fixture_record(job["expectations"])
                self.assertEqual(
                    expectations["classification"], "student-runtime-failure"
                )
                self.assertEqual(expectations["score"], {"exactly": 0})
                expectations["classification"] = "unknown-runtime-outcome"
                with self.assertRaisesRegex(g.JobError, "unknown-runtime-outcome"):
                    g.validate("grading-job", job)
            finally:
                shutil.rmtree(job.root)

    def test_runtime_failure_starter_reaches_prepared_job(self) -> None:
        manifest = fixtures.manifest()
        manifest["projects"][0]["check"]["verification-expectations"] = {
            "starter": {"classification": "student-runtime-failure"},
        }
        with tempfile.TemporaryDirectory() as snapshot:
            try:
                scenarios = g.scenario_inventory(manifest, Path(snapshot))
            except g.JobError:
                self.fail(
                    "Штатный inventory отверг существующую классификацию student-runtime-failure"
                )
            self.assertEqual([entry["scenario"] for entry in scenarios], ["starter"])
            job = g.prepare_job(
                manifest,
                Path(snapshot),
                "demo/exr-answer",
                "starter",
                registry=fixtures.registry(),
            )
            try:
                self.assertEqual(
                    fixture_record(job["expectations"])["classification"],
                    "student-runtime-failure",
                )
            finally:
                shutil.rmtree(job.root)

    def test_author_expectations_accept_runtime_failure(self) -> None:
        for scenario in ("reference", "starter"):
            with self.subTest(scenario=scenario):
                check = fixture_record(
                    copy.deepcopy(fixtures.manifest()["projects"][0]["check"])
                )
                check["verification-expectations"] = {
                    scenario: {"classification": "student-runtime-failure"},
                }
                try:
                    g.validate("project-check", check)
                except g.JobError:
                    self.fail(
                        "Авторская схема отвергла существующую классификацию student-runtime-failure"
                    )

    def test_unknown_classification_remains_rejected(self) -> None:
        for scenario in ("reference", "starter"):
            for schema in ("project-check", "native-checks"):
                with self.subTest(scenario=scenario, schema=schema):
                    manifest = fixtures.manifest()
                    check = fixture_record(manifest["projects"][0]["check"])
                    check["verification-expectations"] = {
                        scenario: {"classification": "unknown-runtime-outcome"},
                    }
                    with self.assertRaises(g.JobError):
                        g.validate(
                            schema, check if schema == "project-check" else manifest
                        )

    def test_unknown_contract_classification_remains_rejected(self) -> None:
        cases = {
            "schemaVersion": 1,
            "cases": [
                {
                    "id": "runtime",
                    "sources": [
                        {"fixture": "tests/runtime.java", "submission": "Answer.java"}
                    ],
                    "expected": {"classification": "unknown-runtime-outcome"},
                }
            ],
        }
        with self.assertRaisesRegex(g.JobError, "unknown-runtime-outcome"):
            g.validate("contract-cases", cases)


if __name__ == "__main__":
    unittest.main()
