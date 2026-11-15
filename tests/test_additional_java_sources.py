"""Реальные дополнительные public sources и отказ unsafe ZIP до компиляции."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeAlias, runtime_checkable
import base64
from selected_job_fixture import (
    GradingJobs,
    fixture_list,
    fixture_record,
    fixture_run_job,
    fixture_set_up,
    fixture_text,
    native_manifest,
)


import hashlib
import io
import json
import stat
import struct
import unittest
import warnings
import zipfile
from pathlib import Path
import test_grading_job as fixtures

grader = fixtures.grader
POLICY: dict[str, object] = {
    "archive": "additional-sources.zip",
    "maxFiles": 128,
    "maxFileBytes": 1048576,
    "maxTotalBytes": 4194304,
    "maxArchiveBytes": 2097152,
}


ZipEntry: TypeAlias = tuple[str | zipfile.ZipInfo, str | bytes]


@runtime_checkable
class _ConfigValidator(Protocol):
    def __call__(self, config: object) -> None: ...


def validate_config(value: object) -> None:
    validate: object = getattr(grader, "validate_config", None)
    if not isinstance(validate, _ConfigValidator):
        raise AssertionError("Канонический config validator недоступен")
    validate(value)


def archive(
    entries: Iterable[ZipEntry], compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(out, "w", compression=compression) as z:
            for name, data in entries:
                z.writestr(name, data)
    return out.getvalue()


class AdditionalJavaSourcesTests(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    setUp = fixture_set_up(fixtures.JUnitJob.setUp)
    run_job = fixture_run_job(fixtures.JUnitJob.run_job)

    def policy(self, **overrides: object) -> None:
        self.cfg["additionalJavaSources"] = {**POLICY, **overrides}

    def zip(
        self, entries: Iterable[ZipEntry], compression: int = zipfile.ZIP_DEFLATED
    ) -> bytes:
        data = archive(entries, compression)
        (self.job / "student/additional-sources.zip").write_bytes(data)
        return data

    def api(self) -> None:
        fixture_list(self.cfg["testFiles"]).append("ApiContract.java")
        self.cfg["apiPrecheck"] = {
            "files": ["ApiContract.java"],
            "entry": "ApiContract",
        }
        (self.job / "tests/ApiContract.java").write_text(
            'import org.prairielearn.api.PlatformApiPrecheck; public class ApiContract {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.method("Student","answer",int.class,9,0);}}'
        )

    def test_optional_primary_zip_only_arbitrary_namespace(self) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Student.java").unlink()
        (self.job / "tests/AnswerTest.java").write_text(
            fixtures.TEST.replace('"Student"', '"other.Solution"')
        )
        self.zip(
            [
                (
                    "other/Solution.java",
                    "package other; public class Solution {public static int answer(){return 42;}}",
                )
            ]
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "success", r)
        self.assertEqual(r["score"], 1)

    def test_optional_union_preserves_fixed_api_and_all_real_sources(self) -> None:
        self.policy(primaryRequired=False)
        self.api()
        (self.job / "student/Student.java").unlink()
        self.zip(
            [
                (
                    "Student.java",
                    "public class Student {public static int answer(){return 42;}}",
                )
            ]
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "success", r)
        self.assertEqual(r["apiPrecheck"], "success")
        self.zip(
            [
                (
                    "other/Solution.java",
                    "package other; public class Solution {public static int answer(){return 42;}}",
                )
            ]
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "student-api-mismatch", r)
        self.assertEqual(r["dependentExecution"], "not-run")
        (self.job / "student/Student.java").write_text(
            "public class Student extends Base {}"
        )
        self.zip(
            [
                (
                    "Base.java",
                    "public class Base {public static int answer(){return 42;}}",
                )
            ]
        )
        self.assertEqual(self.run_job()["classification"], "success")
        self.zip(
            [
                (
                    "Base.java",
                    "public class Base {public static int answer(){return 42;}}",
                ),
                ("Broken.java", "not Java"),
            ]
        )
        self.assertEqual(
            self.run_job()["classification"], "student-compilation-failure"
        )

    def test_required_primary_is_satisfied_by_its_exact_archive_path(self) -> None:
        (self.job / "student/Student.java").unlink()
        for required in [None, True]:
            self.policy(**({} if required is None else {"primaryRequired": required}))
            self.zip(
                [
                    (
                        "Student.java",
                        "public class Student {public static int answer(){return 42;}}",
                    )
                ]
            )
            r = self.run_job()
            self.assertEqual(r["classification"], "success", r)
            self.assertEqual(r["score"], 1)

    def test_optional_direct_primary_needs_no_archive(self) -> None:
        self.policy(primaryRequired=False)
        r = self.run_job()
        self.assertEqual(r["classification"], "success", r)
        self.assertEqual(r["score"], 1)
        self.assertNotIn("additionalSources", r)

    def test_optional_empty_union_is_invalid_without_score(self) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Student.java").unlink()
        empty_archives: list[list[ZipEntry] | None] = [None, [], [("empty/", "")]]
        for entries in empty_archives:
            if entries is not None:
                self.zip(entries)
            r = self.run_job()
            self.assertFalse(r["gradable"])
            self.assertNotIn("score", r)
            self.assertNotEqual(r["classification"], "success")

    def test_optional_duplicate_present_primary_and_trusted_paths_are_refused(
        self,
    ) -> None:
        self.policy(primaryRequired=False)
        for name in [
            "Student.java",
            "grading-job.json",
            "tests/grading-job.json",
            "../Escape.java",
        ]:
            with self.subTest(name=name):
                self.rejected(archive([(name, "class Collision {}")]))

    def test_optional_trusted_common_paths_and_generated_namespaces_stay_protected(
        self,
    ) -> None:
        self.policy(primaryRequired=False)
        (self.job / "student/Student.java").unlink()
        common = self.job / "tests/common/Helper.java"
        common.parent.mkdir()
        common.write_text("package common; public class Helper {}")
        fixture_list(self.cfg["testFiles"]).append("common/Helper.java")
        self.zip([("common/Helper.java", "package common; public class Helper {}")])
        collision = self.run_job()
        self.assertEqual(collision["classification"], "unsafe-submission", collision)
        self.assertNotIn("score", collision)
        self.zip(
            [
                ("other/Solution.java", "package other; public class Solution {}"),
                (
                    "org/prairielearn/Fake.java",
                    "package org.prairielearn; public class Fake {}",
                ),
            ]
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "unsafe-submission", r)
        self.assertNotIn("score", r)

    def test_optional_caps_keep_existing_bounded_admission(self) -> None:
        self.policy(primaryRequired=False, maxFiles=1)
        (self.job / "student/Student.java").unlink()
        self.rejected(archive([("A.java", "class A {}"), ("B.java", "class B {}")]))

    def test_optional_missing_is_distinct_from_unsafe_primary(self) -> None:
        self.policy(primaryRequired=False)
        primary = self.job / "student/Student.java"
        primary.unlink()
        self.zip(
            [
                (
                    "Student.java",
                    "public class Student {public static int answer(){return 42;}}",
                )
            ]
        )
        primary.symlink_to(self.job / "missing.java")
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)
        primary.unlink()
        primary.mkdir()
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)
        primary.rmdir()
        primary.write_bytes(b"x" * (1048576 + 1))
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)
        primary.unlink()
        self.cfg["sourceFiles"] = ["nested/Student.java"]
        (self.job / "student/nested").symlink_to(
            self.job / "absent-directory", target_is_directory=True
        )
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)

    def test_optional_boolean_is_typed_in_all_closed_schemas(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "optional_jobs", Path(__file__).parents[1] / "tools/grading_job.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        jobs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs)
        if not isinstance(jobs, GradingJobs):
            raise AssertionError("Контракт grading_job недоступен")
        for value in [False, True]:
            self.policy(primaryRequired=value)
            validate_config(self.cfg)
            jobs.validate("grading-descriptor", self.cfg)
            jobs.validate_profile(
                {
                    "runtime": "java25-junit-v1",
                    "sourceProfile": {
                        "mode": "implementation",
                        "root": "student",
                        "include": ["*.java"],
                    },
                    "additional-java-sources": {
                        "archive": "additional-sources.zip",
                        "max-files": 128,
                        "max-file-bytes": 1048576,
                        "max-total-bytes": 4194304,
                        "max-archive-bytes": 2097152,
                        "primary-required": value,
                    },
                }
            )
        invalid_values: list[object] = [0, 1, "false", None, []]
        for value in invalid_values:
            self.policy(primaryRequired=value)
            with self.assertRaises(grader.GraderError):
                validate_config(self.cfg)
            with self.assertRaises(jobs.JobError):
                jobs.validate("grading-descriptor", self.cfg)

    def test_four_public_files_two_packages_feed_one_explicit_compile(self) -> None:
        self.policy()
        self.api()
        (self.job / "student/Student.java").write_text(
            "public class Student extends base.Base {}"
        )
        self.zip(
            [
                (
                    "base/Base.java",
                    "package base; public class Base {public static int answer(){return left.Helper.value()+right.Helper.value();}}",
                ),
                (
                    "left/Helper.java",
                    "package left; public class Helper {public static int value(){return 17;}}",
                ),
                (
                    "right/Helper.java",
                    "package right; public class Helper {public static int value(){return 25;}}",
                ),
            ]
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "success", r)
        self.assertEqual(r["apiPrecheck"], "success")
        self.assertEqual(r["score"], 1)
        evidence = fixture_record(r["additionalSources"])
        self.assertNotIn("archiveSha256", evidence)
        self.assertEqual(
            [
                x["bytes"]
                for item in fixture_list(evidence["files"])
                for x in [fixture_record(item)]
            ],
            [
                len(text.encode("utf-8"))
                for _, text in [
                    (
                        "base/Base.java",
                        "package base; public class Base {public static int answer(){return left.Helper.value()+right.Helper.value();}}",
                    ),
                    (
                        "left/Helper.java",
                        "package left; public class Helper {public static int value(){return 17;}}",
                    ),
                    (
                        "right/Helper.java",
                        "package right; public class Helper {public static int value(){return 25;}}",
                    ),
                ]
            ],
        )
        self.assertEqual(
            [
                x["path"]
                for item in fixture_list(evidence["files"])
                for x in [fixture_record(item)]
            ],
            ["base/Base.java", "left/Helper.java", "right/Helper.java"],
        )
        self.assertFalse((self.job / "student/base").exists())
        self.assertFalse((self.job / "student/left").exists())

    def test_default_package_base_and_safe_directories(self) -> None:
        self.policy()
        (self.job / "student/Student.java").write_text(
            "public class Student extends Base {}"
        )
        self.zip(
            [
                ("unused/", ""),
                (
                    "Base.java",
                    "public class Base {public static int answer(){return 42;}}",
                ),
            ],
            zipfile.ZIP_STORED,
        )
        self.assertEqual(self.run_job()["score"], 1)

    def test_safe_directory_can_share_parent_of_trusted_source(self) -> None:
        self.policy()
        (self.job / "tests/pkg").mkdir()
        (self.job / "tests/AnswerTest.java").rename(
            self.job / "tests/pkg/AnswerTest.java"
        )
        self.cfg["testFiles"] = ["pkg/AnswerTest.java"]
        self.zip(
            [("pkg/", ""), ("pkg/Helper.java", "package pkg; public class Helper {}")]
        )
        self.assertEqual(self.run_job()["classification"], "success")

    def test_optional_absent_does_not_change_existing_job(self) -> None:
        self.policy()
        self.assertEqual(self.run_job()["score"], 1)

    def test_archive_with_no_policy_cannot_join_compile_list(self) -> None:
        (self.job / "student/Student.java").write_text(
            "public class Student extends Base {}"
        )
        self.zip(
            [
                (
                    "Base.java",
                    "public class Base {public static int answer(){return 42;}}",
                )
            ]
        )
        self.assertEqual(
            self.run_job()["classification"], "student-compilation-failure"
        )

    def test_bad_java_and_missing_api_are_distinct_from_unsafe_zip(self) -> None:
        self.policy()
        self.api()
        self.zip([("Base.java", "not java")])
        r = self.run_job()
        self.assertEqual(r["classification"], "student-compilation-failure")
        self.assertEqual(r["apiPrecheck"], "not-run")
        self.zip([("Base.java", "public class Base {}")])
        (self.job / "student/Student.java").write_text(
            "public class Student extends Base {}"
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "student-api-mismatch")
        self.assertEqual(r["studentCompilation"], "success")
        self.assertEqual(r["dependentExecution"], "not-run")

    def rejected(self, data: bytes) -> None:
        (self.job / "student/additional-sources.zip").write_bytes(data)
        r = self.run_job()
        self.assertEqual(r["classification"], "unsafe-submission", r)
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)
        self.assertEqual(r["trustedCompilation"], "not-run")
        self.assertIn("ZIP", fixture_text(r["format_errors"]))
        self.assertIn("ручн", fixture_text(r["format_errors"]))
        self.assertNotIn("durations", r)
        self.assertFalse((self.job / "student/Good.java").exists())

    def test_unsafe_names_links_duplicates_overwrite_and_prefix_fail_before_any_stage(
        self,
    ) -> None:
        self.policy()
        link = zipfile.ZipInfo("Link.java")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        fifo = zipfile.ZipInfo("Fifo.java")
        fifo.create_system = 3
        fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
        for name in [
            "../Escape.java",
            "/tmp/Escape.java",
            "C:/Escape.java",
            "a\\Escape.java",
            "a//Escape.java",
            "a/./Escape.java",
            ".hidden/Escape.java",
            "Student.java",
            "grading-job.json",
            "data.txt",
            link,
            fifo,
        ]:
            with self.subTest(name=str(name)):
                self.rejected(
                    archive([("Good.java", "class Good {}"), (name, "class Escape {}")])
                )
        for entries in [
            [("A.java", "class A {}"), ("A.java", "class A {}")],
            [("A.java", "class A {}"), ("A.java/B.java", "class B {}")],
            [("a/", ""), ("a", "not directory")],
        ]:
            with self.subTest(entries=entries):
                self.rejected(archive(entries))

    def test_corruption_nul_and_bad_filename_encoding_are_structured(self) -> None:
        self.policy()
        nul = archive([("A.java", "class A {}")]).replace(b"A.java", b"A\x00java")
        badutf = bytearray(archive([("A.java", "class A {}")]))
        for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
            pos = badutf.index(signature)
            flags = struct.unpack_from("<H", badutf, pos + offset)[0]
            struct.pack_into("<H", badutf, pos + offset, flags | 0x800)
        badutf = bytes(badutf).replace(b"A.java", b"\xff.java")
        damaged = bytearray(archive([("A.java", "class A {}" * 100)]))
        pos = damaged.index(b"PK\x03\x04")
        start = (
            pos
            + 30
            + struct.unpack_from("<H", damaged, pos + 26)[0]
            + struct.unpack_from("<H", damaged, pos + 28)[0]
        )
        damaged[start : start + 4] = b"\xff" * 4
        for data in [b"not a zip", nul, badutf, bytes(damaged)]:
            with self.subTest(sha=hashlib.sha256(data).hexdigest()):
                self.rejected(data)

    def test_encrypted_unsupported_crc_and_entry_limit_are_structured(self) -> None:
        self.policy()
        encrypted = bytearray(archive([("A.java", "class A {}")]))
        for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
            pos = encrypted.index(signature)
            flags = struct.unpack_from("<H", encrypted, pos + offset)[0]
            struct.pack_into("<H", encrypted, pos + offset, flags | 1)
        crc = bytearray(archive([("A.java", "class A {}")], zipfile.ZIP_STORED))
        start = crc.index(b"class A {}")
        crc[start] = ord("x")
        for data in [
            bytes(encrypted),
            bytes(crc),
            archive([("A.java", "class A {}")], zipfile.ZIP_BZIP2),
            archive([(f"d{i}/", "") for i in range(257)]),
        ]:
            with self.subTest(sha=hashlib.sha256(data).hexdigest()):
                self.rejected(data)

    def test_staged_sources_keep_a_private_unix_directory_until_cleanup(self) -> None:
        import tempfile
        import threading

        self.policy()
        self.zip([("PrivateProbe.java", "class PrivateProbe {}")])
        seen: list[tuple[Path, int]] = []
        stop = threading.Event()
        base = Path(tempfile.gettempdir())

        def observe() -> None:
            while not stop.is_set():
                for directory in base.glob("java25-job-runtime-*/additional-sources"):
                    try:
                        if (directory / "PrivateProbe.java").is_file():
                            seen.append(
                                (directory, stat.S_IMODE(directory.stat().st_mode))
                            )
                            return
                    except OSError:
                        pass
                stop.wait(0.01)

        thread = threading.Thread(target=observe)
        thread.start()
        try:
            r = self.run_job()
        finally:
            stop.set()
            thread.join(1)
        self.assertEqual(r["classification"], "success")
        self.assertTrue(seen, "real staging directory was not observed")
        self.assertEqual(
            seen[0][1],
            0o700,
            "source staging must remain private even when adapter root becomes traversable",
        )
        self.assertFalse(
            seen[0][0].exists(), "private source staging leaked after grading"
        )

    def test_archive_itself_cannot_be_a_symlink(self) -> None:
        self.policy()
        outside = self.job / "outside.zip"
        outside.write_bytes(archive([("A.java", "class A {}")]))
        (self.job / "student/additional-sources.zip").symlink_to(outside)
        r = self.run_job()
        self.assertEqual(r["classification"], "unsafe-submission")
        self.assertFalse(r["gradable"])
        self.assertNotIn("score", r)

    def test_limits_actual_bytes_count_depth_and_encoding(self) -> None:
        limit_cases: list[tuple[dict[str, object], list[ZipEntry]]] = [
            ({"maxFiles": 1}, [("A.java", "class A {}"), ("B.java", "class B {}")]),
            ({"maxFileBytes": 3}, [("A.java", "class A {}")]),
            (
                {"maxTotalBytes": 12},
                [("A.java", "class A {}"), ("B.java", "class B {}")],
            ),
            ({"maxArchiveBytes": 10}, [("A.java", "class A {}")]),
            ({}, [("/".join(["a"] * 32) + "/A.java", "class A {}")]),
            ({}, [("a" * 510 + ".java", "class A {}")]),
        ]
        for limits, entries in limit_cases:
            with self.subTest(limits=limits, entries=entries):
                self.policy(**limits)
                self.rejected(archive(entries))
        self.policy()
        self.zip([("A.java", b"\xff")])
        r = self.run_job()
        self.assertEqual(r["classification"], "student-compilation-failure")
        self.assertTrue(r["gradable"])
        self.assertEqual(r["score"], 0)

    def test_public_schemas_accept_the_typed_policy_and_128_extras(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "extra_jobs", Path(__file__).parents[1] / "tools/grading_job.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        jobs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs)
        if not isinstance(jobs, GradingJobs):
            raise AssertionError("Контракт grading_job недоступен")
        self.policy()
        jobs.validate("grading-descriptor", self.cfg)
        jobs.validate_profile(
            {
                "runtime": "java25-junit-v1",
                "sourceProfile": {
                    "mode": "implementation",
                    "root": "student",
                    "include": ["*.java"],
                },
                "additional-java-sources": {
                    "archive": "additional-sources.zip",
                    "max-files": 128,
                    "max-file-bytes": 1048576,
                    "max-total-bytes": 4194304,
                    "max-archive-bytes": 2097152,
                },
            }
        )
        self.zip([(f"Extra{i}.java", f"class Extra{i} {{}}") for i in range(128)])
        r = self.run_job()
        self.assertEqual(r["score"], 1)
        self.assertEqual(
            len(fixture_list(fixture_record(r["additionalSources"])["files"])), 128
        )

    def test_closed_policy_rejects_bad_config_and_mutation(self) -> None:
        invalid_policies: list[dict[str, object]] = [
            {**POLICY, "commands": []},
            {**POLICY, "maxFiles": 129},
            {**POLICY, "maxFiles": True},
            {**POLICY, "archive": "../x.zip"},
            {**POLICY, "archive": "grading-job.json"},
            {k: v for k, v in POLICY.items() if k != "maxFiles"},
        ]
        for policy in invalid_policies:
            with self.subTest(policy=policy):
                self.cfg["additionalJavaSources"] = policy
            with self.assertRaises(grader.GraderError):
                self.run_job()
        self.policy()
        self.cfg["mode"] = "student-tests"
        self.cfg["runtime"] = "java25-mutation-v1"
        with self.assertRaises(grader.GraderError):
            self.run_job()


class OptionalPreparationTests(unittest.TestCase):
    def test_reference_and_contract_materialize_and_run_actual_sources(self) -> None:
        import importlib.util
        import shutil
        import tempfile
        from gradle_unit_fixtures import registry

        spec = importlib.util.spec_from_file_location(
            "optional_preparation", Path(__file__).parents[1] / "tools/grading_job.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        jobs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs)
        if not isinstance(jobs, GradingJobs):
            raise AssertionError("Контракт grading_job недоступен")
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = Path(temporary)
            project = snapshot / "tasks/p"
            project.mkdir(parents=True)
            files = {
                "student/Student.java": "class Student {}",
                "reference/other/Solution.java": "package other; public class Solution {public static int answer(){return 42;}}",
                "tests/AnswerTest.java": fixtures.TEST.replace(
                    '"Student"', '"other.Solution"'
                ),
            }
            for name, text in files.items():
                f = project / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
            f = project / "tests/fixtures/only.zip"
            f.parent.mkdir(parents=True)
            f.write_bytes(
                archive(
                    [("other/Solution.java", files["reference/other/Solution.java"])]
                )
            )
            cases = {
                "schemaVersion": 1,
                "cases": [
                    {
                        "id": "only",
                        "sources": [
                            {
                                "fixture": "tests/fixtures/only.zip",
                                "submission": "additional-sources.zip",
                            }
                        ],
                        "expected": {"classification": "success"},
                    }
                ],
            }
            (project / "tests/cases.json").write_text(json.dumps(cases))

            def selected(name: str, out: str) -> dict[str, str]:
                return {
                    "name": out,
                    "target": name,
                    "data": base64.b64encode((project / name).read_bytes()).decode(),
                }

            check: dict[str, object] = {
                "runtime": "java25-gradle-junit-v1",
                "sourceProfile": {
                    "mode": "implementation",
                    "root": "student",
                    "include": ["Student.java"],
                },
                "java-build": {
                    "kind": "gradle-jar-v1",
                    "main-class": "other.Solution",
                    "artifact": "gradeapp.jar",
                },
                "additional-java-sources": {
                    "archive": "additional-sources.zip",
                    "max-files": 128,
                    "max-file-bytes": 1048576,
                    "max-total-bytes": 4194304,
                    "max-archive-bytes": 2097152,
                    "primary-required": False,
                },
                "references": [{"name": "correct", "root": "reference"}],
                "contract-cases": "tests/cases.json",
            }
            fact: dict[str, object] = {
                "qualifiedId": "demo/exr-optional",
                "projectRoot": "p",
                "check": check,
                "sources": [selected("student/Student.java", "Student.java")],
                "trustedTests": [selected("tests/AnswerTest.java", "AnswerTest.java")],
                "references": [
                    {
                        "name": "correct",
                        "sources": [
                            selected(
                                "reference/other/Solution.java", "other/Solution.java"
                            )
                        ],
                    }
                ],
                "contractCases": {
                    "name": "cases.json",
                    "target": "tests/cases.json",
                    "data": base64.b64encode(
                        (project / "tests/cases.json").read_bytes()
                    ).decode(),
                },
                "contractFixtures": [
                    selected("tests/fixtures/only.zip", "additional-sources.zip")
                ],
            }
            manifest = native_manifest(fact)
            for scenario in ["reference:correct", "contract:only"]:
                job = jobs.prepare_job(
                    manifest,
                    snapshot,
                    fixture_text(fact["qualifiedId"]),
                    scenario,
                    registry=registry(),
                )
                try:
                    self.assertFalse(
                        (job.root / "student/Student.java").exists(),
                        "placeholder substituted from starter",
                    )
                    # Компиляция и JUnit выполняют реальные исходники подготовленного ответа.
                    cfg = fixture_record(job["grading"])
                    cfg["runtime"] = "java25-junit-v1"
                    cfg.pop("javaBuild")
                    (job.root / "tests/grading-job.json").write_text(json.dumps(cfg))
                    result = grader.grade(job.root, registry=registry())
                    self.assertEqual(result["classification"], "success", result)
                finally:
                    shutil.rmtree(job.root)
            fixture_record(check["additional-java-sources"])["primary-required"] = True
            with self.assertRaisesRegex(jobs.JobError, "mapping"):
                jobs.prepare_job(
                    manifest,
                    snapshot,
                    fixture_text(fact["qualifiedId"]),
                    "reference:correct",
                    registry=registry(),
                )


if __name__ == "__main__":
    unittest.main()
