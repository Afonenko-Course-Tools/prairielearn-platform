"""Один допустимый состав из отдельных файлов или ZIP, без расширения fixed API."""

import unittest
from collections.abc import Iterable
from pathlib import Path
from selected_job_fixture import fixture_record, fixture_run_job, fixture_set_up
import test_additional_java_sources as helpers
import test_grading_job as fixtures


class UploadedJavaSources(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    setUp = fixture_set_up(fixtures.JUnitJob.setUp)
    run_job = fixture_run_job(fixtures.JUnitJob.run_job)

    def policy(self, **changes: object) -> None:
        self.cfg["additionalJavaSources"] = {**helpers.POLICY, **changes}

    def zip(self, entries: Iterable[helpers.ZipEntry]) -> None:
        (self.job / "student/additional-sources.zip").write_bytes(
            helpers.archive(entries)
        )

    def test_free_primary_accepts_arbitrary_flat_java_filename(self) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Student.java").unlink()
        (self.job / "student/Solution.java").write_text(
            "public class Solution {public static int answer(){return 42;}}"
        )
        (self.job / "tests/AnswerTest.java").write_text(
            fixtures.TEST.replace('"Student"', '"Solution"')
        )
        value = self.run_job()
        self.assertEqual(value["classification"], "success", value)
        self.assertEqual(value["score"], 1)

    def test_fixed_nested_files_can_all_arrive_in_zip(self) -> None:
        self.policy(
            primaryRequired=True,
            allowAdditional=False,
            maxFiles=1,
            maxFileBytes=8,
            maxTotalBytes=8,
        )
        (self.job / "student/Student.java").unlink()
        self.cfg["sourceFiles"] = ["p/Student.java", "p/Base.java", "p/Helper.java"]
        self.zip(
            [
                (
                    "p/Student.java",
                    "package p;public class Student {public static int answer(){return Base.value()+Helper.value();}}",
                ),
                (
                    "p/Base.java",
                    "package p;class Base {static int value(){return 40;}}",
                ),
                (
                    "p/Helper.java",
                    "package p;class Helper {static int value(){return 2;}}",
                ),
            ]
        )
        (self.job / "tests/AnswerTest.java").write_text(
            fixtures.TEST.replace('"Student"', '"p.Student"')
        )
        value = self.run_job()
        self.assertEqual(value["classification"], "success", value)
        self.assertEqual(value["score"], 1)

    def test_fixed_allowlist_rejects_extra_zip_or_flat_sources(self) -> None:
        self.policy(allowAdditional=False)
        for transport in ("flat", "zip"):
            with self.subTest(transport=transport):
                extra = self.job / "student/Extra.java"
                if transport == "flat":
                    extra.write_text("class Extra {}")
                else:
                    extra.unlink()
                    self.zip([("Extra.java", "class Extra {}")])
                value = self.run_job()
                self.assertEqual(value["classification"], "unsafe-submission")
                self.assertNotIn("score", value)

    def test_required_primary_cannot_be_replaced_by_an_unrelated_zip_source(
        self,
    ) -> None:
        self.policy(allowAdditional=False)
        (self.job / "student/Student.java").unlink()
        self.zip([("Other.java", "class Other {}")])
        value = self.run_job()
        self.assertEqual(value["classification"], "unsafe-submission")
        self.assertNotIn("score", value)

    def test_trusted_basename_in_a_different_student_package_is_legal(self) -> None:
        self.policy()
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){return p.AnswerTest.value();}}"
        )
        source = (
            "package p;public class AnswerTest {public static int value(){return 42;}}"
        )
        for transport in ("flat", "zip"):
            with self.subTest(transport=transport):
                path = self.job / "student/AnswerTest.java"
                if transport == "flat":
                    path.write_text(source)
                else:
                    path.unlink()
                    self.zip([("AnswerTest.java", source)])
                value = self.run_job()
                self.assertEqual(value["classification"], "success", value)
                self.assertEqual(value["score"], 1)

    def test_declared_zip_member_runs_with_no_additional_file_count(self) -> None:
        self.policy(primaryRequired=True, allowAdditional=False, maxFiles=1)
        (self.job / "student/Student.java").unlink()
        self.zip(
            [
                (
                    "Student.java",
                    "public class Student {public static int answer(){return 42;}}",
                )
            ]
        )
        result = self.run_job()
        self.assertEqual(result["score"], 1)
        self.assertEqual(fixture_record(result["additionalSources"])["files"], [])

    def test_flat_and_archive_duplicate_is_rejected_before_execution(self) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Extra.java").write_text("class Extra {}")
        self.zip([("Extra.java", "class Extra {}")])
        value = self.run_job()
        self.assertEqual(value["classification"], "unsafe-submission")
        self.assertNotIn("score", value)

    def test_flat_and_zip_share_the_same_file_count_cap(self) -> None:
        self.policy(primaryRequired=False, maxFiles=1)
        (self.job / "student/Extra.java").write_text("class Extra {}")
        self.zip([("Second.java", "class Second {}")])
        value = self.run_job()
        self.assertEqual(value["classification"], "unsafe-submission")
        self.assertNotIn("score", value)

    def test_flat_symlink_is_not_silently_ignored(self) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Extra.java").symlink_to(self.job / "missing.java")
        value = self.run_job()
        self.assertEqual(value["classification"], "unsafe-submission")
        self.assertNotIn("score", value)


if __name__ == "__main__":
    unittest.main()
