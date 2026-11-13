"""Pinned native manual grading boundary и атомарность source patch."""

from pathlib import Path
import importlib.util
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "integer_points_patch", ROOT / "images/prairielearn/patch-integer-manual-points.py"
)
assert SPEC is not None and SPEC.loader is not None
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)
sys.path.insert(0, str(ROOT / "tools"))
import delivery_verification as verification
import grading_job
import test_delivery5 as fixtures


class NativeIntegerManualPointsPatch(unittest.TestCase):
    def test_real_native_guard_runs_after_all_score_conversions_before_writes(
        self,
    ) -> None:
        source = (
            ROOT / "tests/fixtures/native-credit-upstream/lib/manualGrading.ts"
        ).read_text()
        changed = PATCH.patch(source, "lib/manualGrading.ts")
        guard = changed.index("if (pointPolicy.integer_manual_points)")
        self.assertGreater(guard, changed.index("} else if (score.score_perc != null)"))
        self.assertGreater(guard, changed.index("} else if (score.points != null)"))
        self.assertGreater(guard, changed.index("await insertRubricGrading("))
        self.assertLess(guard, changed.index("sql.insert_grading_job"))
        with self.assertRaisesRegex(ValueError, "Already patched"):
            PATCH.patch(changed, "lib/manualGrading.ts")

    def test_changed_upstream_anchor_rejects_without_partial_source_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "src/schemas/infoCourse.ts"
            schema.parent.mkdir(parents=True)
            schema.write_text("    devModeFeatures: z")
            sync = root / "src/sync/course-db.ts"
            sync.parent.mkdir(parents=True)
            sync.write_text("changed upstream")
            with self.assertRaisesRegex(ValueError, "boundary differs"):
                PATCH.apply(root)
            self.assertEqual(schema.read_text(), "    devModeFeatures: z")
            self.assertEqual(sync.read_text(), "changed upstream")


class IntegerManualPointsDeliveryAdmission(fixtures.DeliveryFixture):
    def test_real_delivery_admits_boolean_policy_without_mutating_official_schema(
        self,
    ) -> None:
        schema = ROOT / "schemas/native-upstream/infoCourse.json"
        original = schema.read_bytes()
        for enabled in [True, False]:
            course = self.read_json("infoCourse.json")
            course["options"] = {"integerManualPoints": enabled}
            self.put("infoCourse.json", course)
            self.assertEqual(
                verification.package_integrity(self.d, self.root)["status"], "success"
            )
        self.assertEqual(schema.read_bytes(), original)

    def test_real_delivery_rejects_nonboolean_and_other_unknown_options(self) -> None:
        for options in [
            {"integerManualPoints": 1},
            {"integerManualPoints": "true"},
            {"integerManualPoints": None},
            {"integerManualPoints": True, "unknown": True},
        ]:
            course = self.read_json("infoCourse.json")
            course["options"] = options
            self.put("infoCourse.json", course)
            with (
                self.subTest(options=options),
                self.assertRaisesRegex(
                    grading_job.JobError, "Invalid native infoCourse.json"
                ),
            ):
                verification.package_integrity(self.d, self.root)


if __name__ == "__main__":
    unittest.main()
