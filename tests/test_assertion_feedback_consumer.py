"""Адресные receiver controls C3 M1/M2: один decoder до native projection."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Literal, TypedDict

if TYPE_CHECKING:
    from junit_result import JUnitCounts
from pathlib import Path
from unittest.mock import patch
import unittest

import test_assertion_feedback as af
from json_boundary import is_list, is_object
import test_grading_job as fixtures


class ConsumerResult(TypedDict):
    classification: str
    gradable: bool
    score: float
    counts: JUnitCounts


class ConsumerGuards(unittest.TestCase):
    def result(self) -> ConsumerResult:
        return {
            "classification": "success",
            "gradable": True,
            "score": 1,
            "counts": af.CheckShape().counts(),
        }

    def test_invalid_protocol_cannot_bypass_native_decoder(self) -> None:
        for protocol in (True, 3, 1):
            result = self.result()
            result["counts"]["feedbackProtocolVersion"] = protocol
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                af.feedback(result, {})

    def test_protocol_one_and_legacy_without_checks_keep_leaf_points(self) -> None:
        for explicit in (True, False):
            result = self.result()
            result["counts"]["cases"][0].pop("checks")
            result["counts"]["feedbackProtocolVersion"] = 1
            if not explicit:
                result["counts"].pop("feedbackProtocolVersion")
            af.validate_counts(result["counts"])
            native = af.feedback(result, {})
            self.assertEqual((af.public_score(native), len(af.public_tests(native))), (1, 1))
            self.assertNotIn("checks", af.public_cases(native)[0])

    def test_mutation_protocol_one_may_omit_case_projection(self) -> None:
        result = self.result()
        result["counts"].update(feedbackProtocolVersion=1, cases=[])
        native = af.feedback(result, {"mode": "student-tests"})
        self.assertEqual(af.public_score(native), 1)
        self.assertEqual(af.public_cases(native), [])

    def test_protocol_two_still_requires_case_coverage_in_mutation_descriptor(self) -> None:
        result = self.result()
        result["counts"]["cases"] = []
        with self.assertRaises(ValueError):
            af.feedback(result, {"mode": "student-tests"})

    def test_invalid_complete_counts_cannot_be_silently_projected(self) -> None:
        mutations: tuple[Callable[[JUnitCounts], None], ...] = (
            lambda c: c.update(feedbackProtocolVersion=2, complete=False),
            lambda c: c.update(passed=2),
            lambda c: c["cases"][0].update(id="foreign"),
        )
        for mutate in mutations:
            result = self.result()
            mutate(result["counts"])
            with self.subTest(counts=result["counts"]), self.assertRaises(ValueError):
                af.feedback(result, {})

    def test_unknown_complete_is_rejected_by_both_boundaries(self) -> None:
        result = self.result()
        af.case_checks(result["counts"]["cases"][0])[0]["delegated"] = "unknown"
        for name, boundary in (
            ("decoder", lambda: af.validate_counts(result["counts"])),
            ("native", lambda: af.feedback(result, {})),
        ):
            with self.subTest(boundary=name), self.assertRaises(ValueError):
                boundary()

    def test_honest_pending_preserves_real_junit_points(self) -> None:
        result = self.result()
        af.case_checks(result["counts"]["cases"][0])[0].update(
            delegated="unknown", availability="incomplete: pending observation"
        )
        af.validate_counts(result["counts"])
        native = af.feedback(result, {})
        self.assertEqual(af.completeness(native), "incomplete")
        self.assertEqual((af.public_score(native), af.public_tests(native)[0]["points"]), (1, 1))

    def test_success_without_optional_checks_has_complete_feedback(self) -> None:
        result = self.result()
        result["counts"]["cases"][0]["checks"] = []
        native = af.feedback(result, {})
        self.assertEqual(af.completeness(native), "complete")
        self.assertEqual((af.public_score(native), af.public_tests(native)[0]["points"]), (1, 1))

    def test_existing_tolerance_is_rendered_without_private_data(self) -> None:
        result = self.result()
        af.case_checks(result["counts"]["cases"][0])[0]["delta"] = "0.25"
        native = af.feedback(result, {})
        self.assertIn("Допуск: 0.25", af.public_tests(native)[0]["message"])


class SignedUnknownGuard(af.ProductionCase):
    def test_broken_signed_unknown_complete_is_infrastructure(self) -> None:
        original = af.grader_run()
        corrupted: list[str] = []

        def invoke(command: Sequence[str], cwd: Path, timeout: float,
                   output_limit: int = 65536, *, env: Mapping[str, str] | None = None
                   ) -> tuple[int, str, Literal["timeout", "output_limit"] | None]:
            params: object = (
                json.loads(Path(command[-1]).read_text())
                if any(arg.endswith("PlatformJUnitAdapter") for arg in command)
                else None
            )
            outcome = original(command, cwd, timeout, output_limit, env=env)
            if params:
                assert is_object(params)
                feedback_file = params["feedback_file"]
                report_key = params["report_key"]
                assert isinstance(feedback_file, str) and isinstance(report_key, str)
                path = Path(feedback_file)
                counts: object = json.loads(path.read_text())
                assert is_object(counts)
                cases = counts["cases"]
                assert is_list(cases)
                case = cases[0]
                assert is_object(case)
                checks = case["checks"]
                assert is_list(checks)
                check = checks[0]
                assert is_object(check)
                self.assertEqual(check["availability"], "complete")
                self.assertEqual(check["delegated"], "returned")
                before = self.preserve(path)
                check["delegated"] = "unknown"
                path.write_text(json.dumps(counts))
                import hmac
                Path(str(path)+'.signature').write_text(hmac.digest(bytes.fromhex(report_key),path.read_bytes(),'sha256').hex())
                after = self.preserve(path)
                corrupted.append(after)
                self.calls[-1]["brokenProducer"] = {
                    "beforeSha256": before,
                    "afterSha256": after,
                    "mutation": "cases[0].checks[0].delegated returned→unknown",
                    "operatorAuthenticatedBrokenProducer": True,
                }
            return outcome

        with patch.object(fixtures.grader, "_run", invoke):
            with self.assertRaisesRegex(
                fixtures.grader.GraderError, "Invalid assertion"
            ):
                self.run_job()
        self.assertEqual(len(corrupted), 1)


if __name__ == "__main__":
    unittest.main()
