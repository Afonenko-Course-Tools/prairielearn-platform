"""Lifecycle обычного builder; faults и все outputs ограничены внешним temp."""

import errno
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_build_course_launch import LaunchContract, builder


class PublicationLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.export = LaunchContract()
        self.export.setUp()
        self.addCleanup(self.export.doCleanups)
        self.export.run_spy = self.export.emit_package
        self.checks = self.export.output.with_name(
            self.export.output.name + "-checks.json"
        )

    def assert_no_stages(self) -> None:
        self.assertFalse(self.export.stage.exists())
        self.assertFalse(
            any(p.name.startswith(".pl-export-") for p in self.export.root.iterdir())
        )

    def test_output_collision_removes_own_checks_and_allows_retry(self) -> None:
        emit = self.export.emit_package

        def compete(*args, **kwargs):
            result = emit(*args, **kwargs)
            if args[0][0] == "quarto":
                self.export.output.mkdir()
            return result

        self.export.run_spy = compete
        with self.assertRaisesRegex(builder.BuildError, "Cannot publish fresh output"):
            self.export.call(export_stage=self.export.stage)
        self.assertTrue(self.export.output.is_dir())
        self.assertEqual(list(self.export.output.iterdir()), [])
        self.assertFalse(self.checks.exists())
        self.assert_no_stages()
        self.export.output.rmdir()
        self.export.run_spy = emit
        self.export.call(export_stage=self.export.stage)
        self.assertTrue((self.export.output / "delivery.json").is_file())

    def test_competing_checks_file_is_preserved(self) -> None:
        emit = self.export.emit_package

        def compete(*args, **kwargs):
            result = emit(*args, **kwargs)
            if args[0][0] == "quarto":
                self.checks.write_text("FOREIGN")
            return result

        self.export.run_spy = compete
        with self.assertRaises(FileExistsError):
            self.export.call(export_stage=self.export.stage)
        self.assertEqual(self.checks.read_text(), "FOREIGN")
        self.assertFalse(self.export.output.exists())
        self.assert_no_stages()

    def test_failure_immediately_after_checks_allocation_cleans_and_retries(
        self,
    ) -> None:
        with patch("os.fchmod", side_effect=OSError(errno.EIO, "CHECKS_WRITE_FAILURE")):
            with self.assertRaisesRegex(OSError, "CHECKS_WRITE_FAILURE"):
                self.export.call(export_stage=self.export.stage)
        self.assertFalse(self.checks.exists())
        self.assert_no_stages()
        self.export.call(export_stage=self.export.stage)
        self.assertTrue(self.checks.is_file())

    def test_cleanup_failure_keeps_primary_publication_error(self) -> None:
        unlink = Path.unlink

        def refuse_checks(path: Path, *args, **kwargs):
            if path == self.checks:
                raise OSError("SECONDARY_CLEANUP_FAILURE")
            return unlink(path, *args, **kwargs)

        with patch.object(
            builder,
            "publish_directory",
            side_effect=builder.BuildError("PRIMARY_PUBLICATION_FAILURE"),
        ):
            with patch.object(Path, "unlink", refuse_checks):
                with self.assertRaisesRegex(
                    builder.BuildError, "PRIMARY_PUBLICATION_FAILURE"
                ) as caught:
                    self.export.call(export_stage=self.export.stage)
        self.assertTrue(
            any(
                "SECONDARY_CLEANUP_FAILURE" in note
                for note in caught.exception.__notes__
            )
        )
        self.assert_no_stages()

    def test_rollback_preserves_foreign_replacement_of_own_checks(self) -> None:
        def replaced(*args, **kwargs):
            self.checks.unlink()
            self.checks.write_text("FOREIGN_REPLACEMENT")
            raise builder.BuildError("PUBLICATION_REFUSED")

        with patch.object(builder, "publish_directory", replaced):
            with self.assertRaisesRegex(builder.BuildError, "PUBLICATION_REFUSED"):
                self.export.call(export_stage=self.export.stage)
        self.assertEqual(self.checks.read_text(), "FOREIGN_REPLACEMENT")
        self.assert_no_stages()

    def test_untrusted_assessment_uuid_cannot_collide_with_question(self) -> None:
        emit = self.export.emit_package

        def collision(*args, **kwargs):
            result = emit(*args, **kwargs)
            if args[0][0] == "quarto":
                native = Path(args[0][4])
                question = next((native / "questions").rglob("info.json"))
                assessment = next(
                    (native / "courseInstances").rglob("infoAssessment.json")
                )
                value = json.loads(assessment.read_text())
                value["uuid"] = json.loads(question.read_text())["uuid"].upper()
                assessment.write_text(json.dumps(value))
            return result

        self.export.run_spy = collision
        with self.assertRaisesRegex(builder.BuildError, "UUID collision"):
            self.export.call(export_stage=self.export.stage)
        self.assertFalse(self.export.output.exists())
        self.assertFalse(self.checks.exists())
        self.assert_no_stages()


if __name__ == "__main__":
    unittest.main()
