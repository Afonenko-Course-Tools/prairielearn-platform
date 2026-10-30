"""Адресные receiver controls C3 M1/M2: один decoder до native projection."""

import json
from pathlib import Path
from unittest.mock import patch
import unittest

import test_assertion_feedback as af
import test_grading_job as fixtures


class ConsumerGuards(unittest.TestCase):
    def result(self):
        return {
            "classification": "success",
            "gradable": True,
            "score": 1,
            "counts": af.CheckShape().counts(),
        }

    def test_invalid_protocol_cannot_bypass_native_decoder(self):
        for protocol in (True, 3, 1):
            result = self.result()
            result["counts"]["feedbackProtocolVersion"] = protocol
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                af.feedback(result, {})

    def test_protocol_one_and_legacy_without_checks_keep_leaf_points(self):
        for explicit in (True, False):
            result = self.result()
            result["counts"]["cases"][0].pop("checks")
            result["counts"]["feedbackProtocolVersion"] = 1
            if not explicit:
                result["counts"].pop("feedbackProtocolVersion")
            af.helpers["validate_counts"](result["counts"])
            native = af.feedback(result, {})
            self.assertEqual((native["score"], len(native["tests"])), (1, 1))
            self.assertNotIn("checks", native["feedback"]["cases"][0])

    def test_mutation_protocol_one_may_omit_case_projection(self):
        result = self.result()
        result["counts"].update(feedbackProtocolVersion=1, cases=[])
        native = af.feedback(result, {"mode": "student-tests"})
        self.assertEqual(native["score"], 1)
        self.assertEqual(native["feedback"]["cases"], [])

    def test_protocol_two_still_requires_case_coverage_in_mutation_descriptor(self):
        result = self.result()
        result["counts"]["cases"] = []
        with self.assertRaises(ValueError):
            af.feedback(result, {"mode": "student-tests"})

    def test_invalid_complete_counts_cannot_be_silently_projected(self):
        for mutate in (
            lambda c: c.update(feedbackProtocolVersion=2, complete=False),
            lambda c: c.update(passed=2),
            lambda c: c["cases"][0].update(id="foreign"),
        ):
            result = self.result()
            mutate(result["counts"])
            with self.subTest(counts=result["counts"]), self.assertRaises(ValueError):
                af.feedback(result, {})

    def test_unknown_complete_is_rejected_by_both_boundaries(self):
        result = self.result()
        result["counts"]["cases"][0]["checks"][0]["delegated"] = "unknown"
        for name, boundary in (
            ("decoder", lambda: af.helpers["validate_counts"](result["counts"])),
            ("native", lambda: af.feedback(result, {})),
        ):
            with self.subTest(boundary=name), self.assertRaises(ValueError):
                boundary()

    def test_honest_pending_preserves_real_junit_points(self):
        result = self.result()
        result["counts"]["cases"][0]["checks"][0].update(
            delegated="unknown", availability="incomplete: pending observation"
        )
        af.helpers["validate_counts"](result["counts"])
        native = af.feedback(result, {})
        self.assertEqual(native["feedback"]["feedbackCompleteness"], "incomplete")
        self.assertEqual((native["score"], native["tests"][0]["points"]), (1, 1))


class SignedUnknownGuard(af.ProductionCase):
    def test_broken_signed_unknown_complete_is_infrastructure(self):
        original = fixtures.grader._run
        corrupted = []

        def invoke(command, *args, **kwargs):
            params = (
                json.loads(Path(command[-1]).read_text())
                if "PlatformJUnitAdapter" in command
                else None
            )
            outcome = original(command, *args, **kwargs)
            if params:
                path = Path(params["counts_file"])
                counts = json.loads(path.read_text())
                check = counts["cases"][0]["checks"][0]
                self.assertEqual(check["availability"], "complete")
                self.assertEqual(check["delegated"], "returned")
                self.assertEqual(counts["signature"], params["signature"])
                before = self.preserve(path)
                check["delegated"] = "unknown"
                path.write_text(json.dumps(counts))
                after = self.preserve(path)
                corrupted.append(after)
                self.calls[-1]["brokenProducer"] = {
                    "beforeSha256": before,
                    "afterSha256": after,
                    "mutation": "cases[0].checks[0].delegated returned→unknown",
                    "signaturePreserved": True,
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
