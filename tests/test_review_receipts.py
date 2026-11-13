"""Результаты grading: полнота сценариев, образы и ожидаемые ошибки."""

from gradle_unit_fixtures import registry as unit_registry
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import grading_job as g
from grading_types import Scenario, UnavailableReference

IMAGE = "registry.example/runtime@sha256:" + "a" * 64


def result(scenario: str = "starter", image: str = IMAGE) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "scope": "delivery",
        "backend": "container",
        "qualifiedId": "demo/exr-a",
        "scenario": scenario,
        "runtime": "java25-junit-v1",
        "imageDigest": image,
        "gradable": True,
        "studentCompilation": "success",
        "trustedCompilation": "success",
        "infrastructure": "complete",
        "classification": "success",
        "counts": {
            "discovered": 1,
            "executed": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "aborted": 0,
            "containerFailures": 0,
            "outcomes": {"T#t": "successful"},
            "complete": True,
            "eventErrors": 0,
            "registered": ["T#t"],
            "started": ["T#t"],
            "failureKinds": {},
            "cases": [{"id": "T#t", "name": "Проверка результата", "status": "passed"}],
        },
        "score": 1,
        "maxPoints": 1,
        "rawResult": {
            "score": 1,
            "points": 1,
            "max_points": 1,
            "output": "",
            "message": "",
            "gradable": True,
            "tests": [
                {
                    "name": "t",
                    "description": "",
                    "points": 1,
                    "max_points": 1,
                    "output": "",
                    "message": "",
                }
            ],
        },
        "durations": {"execution": 1},
        "diagnostics": {},
        "toolchain": "JDK25",
        "containment": "official-landlock-sbuser",
        "scoring": {"mode": "weighted"},
        "output": "",
    }


class ReviewReceipts(unittest.TestCase):
    def test_starter_only_cannot_claim_complete_scenario_coverage(self) -> None:
        receipt = g.verify_results([result()], {}, registry=unit_registry())
        self.assertEqual(receipt.get("coverage"), "partial")

    def test_mixed_image_for_same_runtime_is_rejected(self) -> None:
        with self.assertRaises(g.JobError):
            g.verify_results(
                [
                    result(),
                    result(
                        "reference:default",
                        "registry.example/runtime@sha256:" + "d" * 64,
                    ),
                ],
                {},
                registry=unit_registry(),
            )

    def test_negative_compilation_contract_matches_without_defect(self) -> None:
        r = result("contract:invalid")
        for k in [
            "counts",
            "score",
            "maxPoints",
            "rawResult",
            "durations",
            "diagnostics",
            "toolchain",
            "containment",
            "scoring",
        ]:
            r.pop(k)
        r.update(
            gradable=True,
            score=0,
            studentCompilation="failure",
            trustedCompilation="not-run",
            classification="student-compilation-failure",
            format_errors="invalid source",
        )
        receipt = g.verify_results(
            [r],
            {
                "contract:invalid": {
                    "student-compilation": "failure",
                    "job": "complete",
                    "classification": "student-compilation-failure",
                }
            },
            registry=unit_registry(),
        )
        self.assertEqual(receipt["exitCode"], 0)

    def test_minimal_claimed_success_is_schema_invalid(self) -> None:
        r = {
            k: result()[k]
            for k in [
                "schemaVersion",
                "scope",
                "qualifiedId",
                "scenario",
                "runtime",
                "infrastructure",
                "classification",
            ]
        }
        with self.assertRaises(g.JobError):
            g.validate("check-result", r)

    def test_success_cannot_contain_infrastructure_error(self) -> None:
        r = result()
        r["grading_error"] = True
        with self.assertRaises(g.JobError):
            g.validate("check-result", r)

    def test_resolved_descriptor_requires_full_nested_options(self) -> None:
        cfg = {
            "schemaVersion": 1,
            "sourceFiles": ["S.java"],
            "testFiles": ["T.java"],
            "mode": "implementation",
            "runtime": "java25-junit-v1",
            "java": {},
            "limits": {},
            "scoring": {"mode": "weighted"},
            "discovery": {},
        }
        with self.assertRaises(g.JobError):
            g.validate("grading-descriptor", cfg)

    def test_complete_receipt_records_optional_reference_unavailability(self) -> None:
        required: list[Scenario] = [
            {
                "qualifiedId": "demo/exr-a",
                "scenario": "reference:optional",
                "optional": True,
            },
            {"qualifiedId": "demo/exr-a", "scenario": "starter", "optional": False},
        ]
        unavailable: list[UnavailableReference] = [
            {
                "qualifiedId": "demo/exr-a",
                "scenario": "reference:optional",
                "status": "reference-unavailable",
            }
        ]
        receipt = g.verify_results(
            [result()], {}, required, unavailable, registry=unit_registry()
        )
        self.assertEqual(receipt["coverage"], "complete")
        self.assertEqual(receipt["unavailableReferences"], unavailable)

    def test_nested_variant_outcome_cannot_omit_compilation_counts_and_raw_results(
        self,
    ) -> None:
        r = result()
        r.pop("counts")
        r.pop("rawResult")
        r["variants"] = {
            "correct": {"infrastructure": "complete", "classification": "success"},
            "mutant": {
                "infrastructure": "complete",
                "classification": "behavior-failure",
            },
        }
        with self.assertRaises(g.JobError):
            g.validate("check-result", r)

    def test_required_reference_cannot_be_marked_unavailable(self) -> None:
        required: list[Scenario] = [
            {
                "qualifiedId": "demo/exr-a",
                "scenario": "reference:default",
                "optional": False,
            },
            {"qualifiedId": "demo/exr-a", "scenario": "starter", "optional": False},
        ]
        with self.assertRaises(g.JobError):
            g.verify_results(
                [result()],
                {},
                required,
                [
                    {
                        "qualifiedId": "demo/exr-a",
                        "scenario": "reference:default",
                        "status": "reference-unavailable",
                    }
                ],
                registry=unit_registry(),
            )

    def test_single_question_cannot_switch_between_runtime_profiles(self) -> None:
        a = result()
        b = result("reference:default")
        b["runtime"] = "java25-mutation-v1"
        with self.assertRaises(g.JobError):
            g.verify_results([a, b], {}, registry=unit_registry())

    def test_invalid_starter_cannot_bypass_compilation_gate_with_negative_expectation(
        self,
    ) -> None:
        r = result()
        for k in [
            "counts",
            "score",
            "maxPoints",
            "rawResult",
            "durations",
            "diagnostics",
            "toolchain",
            "containment",
            "scoring",
        ]:
            r.pop(k)
        r.update(
            gradable=True,
            score=0,
            studentCompilation="failure",
            trustedCompilation="not-run",
            classification="student-compilation-failure",
            format_errors="invalid source",
        )
        self.assertEqual(
            g.verify_results(
                [r],
                {"starter": {"student-compilation": "failure"}},
                registry=unit_registry(),
            )["exitCode"],
            1,
        )
