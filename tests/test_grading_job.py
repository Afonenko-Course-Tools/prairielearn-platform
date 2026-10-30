"""Real JUnit jobs expose discovery, isolation and policy mistakes."""

from gradle_unit_fixtures import registry as unit_registry
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.environ["PATH"] = "/usr/lib/jvm/java-25-openjdk/bin:" + os.environ["PATH"]
spec = importlib.util.spec_from_file_location(
    "grader", ROOT / "images/java25-grader/grade.py"
)
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)
TEST = """import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest { @Test void right() throws Exception { assertEquals(42,Class.forName("Student").getMethod("answer").invoke(null)); } }"""


class JUnitJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)
        (self.job / "student").mkdir()
        (self.job / "tests").mkdir()
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){return 42;}}"
        )
        (self.job / "tests/AnswerTest.java").write_text(TEST)
        self.cfg = {
            "schemaVersion": 1,
            "sourceFiles": ["Student.java"],
            "testFiles": ["AnswerTest.java"],
            "mode": "implementation",
            "runtime": "java25-junit-v1",
            "java": {
                "release": 25,
                "encoding": "UTF-8",
                "compiler-options": ["-proc:none", "-Xmaxerrs", "5"],
            },
            "limits": {
                "outer-seconds": 30,
                "compile-seconds": 15,
                "run-seconds": 3,
                "max-output-bytes": 65536,
                "networking": False,
            },
            "scoring": {"mode": "weighted"},
            "discovery": {"min-executed": 1, "allow-skipped": False},
        }

    def run_job(self):
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        return grader.grade(self.job, registry=unit_registry())

    def test_existing_junit_suite_runs_without_course_main(self):
        r = self.run_job()
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["counts"]["executed"], 1)

    def test_trusted_zero_tests_is_infrastructure(self):
        (self.job / "tests/AnswerTest.java").write_text("public class AnswerTest {}")
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_student_compile_error_is_not_infrastructure(self):
        (self.job / "student/Student.java").write_text("not java")
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertEqual(r["classification"], "student-compilation-failure")

    def test_trusted_compile_error_is_infrastructure(self):
        (self.job / "tests/AnswerTest.java").write_text("not java")
        r = self.run_job()
        self.assertEqual(r["classification"], "infrastructure-failure")
        self.assertEqual(r["studentCompilation"], "success")
        self.assertEqual(r["trustedCompilation"], "failure")
        self.assertNotIn("score", r)

    def test_submitted_test_injection_is_not_compiled(self):
        (self.job / "student/AnswerTest.java").write_text("not java")
        self.assertEqual(self.run_job()["score"], 1)

    def test_unsafe_fqcn_collision_rejected(self):
        (self.job / "student/Student.java").write_text("class AnswerTest {}")
        r = self.run_job()
        self.assertFalse(r["gradable"])
        self.assertEqual(r["classification"], "unsafe-submission")

    def test_missing_api_is_behavior_failure(self):
        (self.job / "student/Student.java").write_text("public class Student {}")
        r = self.run_job()
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["classification"], "behavior-failure")

    def test_disabled_trusted_suite_is_not_success(self):
        (self.job / "tests/AnswerTest.java").write_text(
            TEST.replace("@Test", "@org.junit.jupiter.api.Disabled @Test")
        )
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_disabled_container_with_active_test_is_infrastructure(self):
        (self.job / "tests/DisabledTest.java").write_text(
            "import org.junit.jupiter.api.*; @Disabled public class DisabledTest { @Test void skipped(){} }"
        )
        self.cfg["testFiles"].append("DisabledTest.java")
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_weighted_and_all_pass_preserve_raw_outcomes(self):
        (self.job / "tests/AnswerTest.java").write_text(
            TEST.replace(" } }", " } @Test void bad(){fail();} }")
        )
        r = self.run_job()
        self.assertEqual(r["score"], 0.5)
        self.assertEqual(r["maxPoints"], 2)
        self.cfg["scoring"] = {"mode": "all-pass"}
        r = self.run_job()
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["counts"]["passed"], 1)
        self.assertEqual(r["maxPoints"], 2)

    def test_inner_timeout_is_student_failure(self):
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){while(true){}}}"
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "student-timeout")
        self.assertEqual(r["score"], 0)

    def test_output_flood_is_bounded_student_failure(self):
        (self.job / "student/Student.java").write_text(
            'public class Student {public static int answer(){while(true){System.out.println("x".repeat(8192));}}}'
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "student-output-overflow")
        self.assertLessEqual(len(r["output"].encode()), 65536)

    def test_missing_report_is_infrastructure(self):
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){System.exit(0);return 42;}}"
        )
        with self.assertRaises(grader.GraderError):
            self.run_job()

    def test_dependency_hash_mismatch_blocks_preflight(self):
        self.cfg["runtime"] = "unknown"
        with self.assertRaises(grader.GraderError):
            self.run_job()


class MutationJob(unittest.TestCase):
    setUp = JUnitJob.setUp
    run_job = JUnitJob.run_job

    def setup_mutation(self):
        self.cfg.update(
            mode="student-tests",
            runtime="java25-mutation-v1",
            sourceFiles=["AnswerTest.java"],
            testFiles=["variants/correct/Student.java", "variants/wrong/Student.java"],
            variants={"correct": ["correct"], "mutants": ["wrong"]},
            scoring={"mode": "all-pass"},
        )
        (self.job / "student/Student.java").unlink()
        (self.job / "student/AnswerTest.java").write_text(TEST)
        for id, value in [("correct", 42), ("wrong", 41)]:
            p = self.job / f"tests/variants/{id}/Student.java"
            p.parent.mkdir(parents=True)
            p.write_text(
                f"public class Student {{ public static int answer(){{return {value};}} }}"
            )

    def test_duplicate_fixture_fqcn_isolated(self):
        self.setup_mutation()
        r = self.run_job()
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["variants"]["wrong"]["counts"]["failed"], 1)

    def test_submitted_zero_tests_is_quality_failure(self):
        self.setup_mutation()
        (self.job / "student/AnswerTest.java").write_text("public class AnswerTest {}")
        r = self.run_job()
        self.assertEqual(r["classification"], "student-test-quality-failure")
        self.assertEqual(r["score"], 0)

    def test_disabled_mutation_suite_is_not_success(self):
        self.setup_mutation()
        (self.job / "student/AnswerTest.java").write_text(
            TEST.replace("@Test", "@org.junit.jupiter.api.Disabled @Test")
        )
        r = self.run_job()
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["classification"], "student-test-quality-failure")

    def test_broken_mutant_fixture_is_infrastructure(self):
        self.setup_mutation()
        (self.job / "tests/variants/wrong/Student.java").write_text("not java")
        with self.assertRaises(grader.GraderError):
            self.run_job()


class ScoringTests(unittest.TestCase):
    setUp = JUnitJob.setUp
    run_job = JUnitJob.run_job

    def test_contract_groups_use_stable_ids_and_weights(self):
        (self.job / "tests/AnswerTest.java").write_text(
            TEST.replace(" } }", " } @Test void bad(){fail();} }")
        )
        self.cfg["scoring"] = {
            "mode": "contract-groups",
            "groups": [
                {
                    "id": "right",
                    "weight": 3,
                    "tests": [
                        "[engine:junit-jupiter]/[class:AnswerTest]/[method:right()]"
                    ],
                },
                {
                    "id": "bad",
                    "weight": 1,
                    "tests": [
                        "[engine:junit-jupiter]/[class:AnswerTest]/[method:bad()]"
                    ],
                },
            ],
        }
        r = self.run_job()
        self.assertEqual(r["score"], 0.75)
        self.assertEqual(r["rawResult"]["score"], 0.5)

    def test_threshold_uses_declared_basis(self):
        (self.job / "tests/AnswerTest.java").write_text(
            TEST.replace(" } }", " } @Test void bad(){fail();} }")
        )
        self.cfg["scoring"] = {"mode": "threshold", "basis": "passed-tests", "value": 1}
        self.assertEqual(self.run_job()["score"], 1)

    def test_contract_groups_unknown_test_id_is_infrastructure(self):
        self.cfg["scoring"] = {
            "mode": "contract-groups",
            "groups": [{"id": "absent", "weight": 1, "tests": ["absent"]}],
        }
        with self.assertRaises(grader.GraderError):
            self.run_job()


class RuntimeBundleTests(unittest.TestCase):
    def test_unregistered_jar_cannot_join_offline_classpath(self):
        import shutil

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shutil.copytree(ROOT / "runtime", root / "runtime")
            shutil.copyfile(
                ROOT / "runtime-profiles.json", root / "runtime-profiles.json"
            )
            bundle = root / "runtime/java25-junit-v1"
            shutil.copyfile(
                bundle / "json-simple-1.1.1.jar", bundle / "unregistered.jar"
            )
            original = grader.PLATFORM
            grader.PLATFORM = root
            try:
                with self.assertRaises(grader.GraderError):
                    grader.preflight("java25-junit-v1", registry=unit_registry())
            finally:
                grader.PLATFORM = original


class AdditionalSourceDeliveryTests(unittest.TestCase):
    def test_reference_extra_and_contract_zip_are_explicit_hashed_public_private_inputs(
        self,
    ):
        import importlib.util
        import hashlib
        import shutil
        import io
        import zipfile

        spec = importlib.util.spec_from_file_location(
            "additional_jobs", ROOT / "tools/grading_job.py"
        )
        jobs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jobs)
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            project = snapshot / "tasks/p"
            policy = {
                "archive": "additional-sources.zip",
                "max-files": 128,
                "max-file-bytes": 1048576,
                "max-total-bytes": 4194304,
                "max-archive-bytes": 2097152,
            }
            files = {
                "student/Student.java": "public class Student {public static int answer(){return 0;}}",
                "reference/Student.java": "public class Student extends Base {}",
                "reference/Base.java": "public class Base {public static int answer(){return 42;}}",
                "tests/AnswerTest.java": TEST,
                "student/public/PublicTest.java": TEST.replace(
                    "AnswerTest", "PublicTest"
                ),
                "tests/fixtures/Student.java": "public class Student extends Base {}",
            }
            for name, source in files.items():
                f = project / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(source)
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as z:
                z.writestr(
                    "Base.java",
                    "public class Base {public static int answer(){return 42;}}",
                )
            (project / "tests/fixtures/extra.zip").write_bytes(data.getvalue())
            case = {
                "schemaVersion": 1,
                "cases": [
                    {
                        "id": "extra",
                        "sources": [
                            {
                                "fixture": "tests/fixtures/Student.java",
                                "submission": "Student.java",
                            },
                            {
                                "fixture": "tests/fixtures/extra.zip",
                                "submission": "additional-sources.zip",
                            },
                        ],
                        "expected": {
                            "classification": "success",
                            "required-tests": "all-pass",
                        },
                    }
                ],
            }
            (project / "tests/cases.json").write_text(json.dumps(case))

            def select(name, target):
                return {
                    "projectRelativePath": name,
                    "submissionRelativePath": target,
                    "sha256": hashlib.sha256((project / name).read_bytes()).hexdigest(),
                }

            fact = {
                "qualifiedId": "demo/exr-extra",
                "projectRoot": "p",
                "check": {
                    "runtime": "java25-junit-v1",
                    "sourceProfile": {
                        "mode": "implementation",
                        "root": "student",
                        "include": ["*.java"],
                    },
                    "additional-java-sources": policy,
                    "references": [
                        {"name": "correct", "root": "reference", "optional": False}
                    ],
                    "contract-cases": "tests/cases.json",
                },
                "sources": [select("student/Student.java", "Student.java")],
                "trustedTests": [select("tests/AnswerTest.java", "AnswerTest.java")],
                "verificationTests": [
                    select("student/public/PublicTest.java", "PublicTest.java")
                ],
                "references": [
                    {
                        "name": "correct",
                        "sources": [
                            select("reference/Student.java", "Student.java"),
                            select("reference/Base.java", "Base.java"),
                        ],
                    }
                ],
                "contractCasesHash": {
                    "projectRelativePath": "tests/cases.json",
                    "sha256": hashlib.sha256(
                        (project / "tests/cases.json").read_bytes()
                    ).hexdigest(),
                },
                "contractFixtures": [
                    select("tests/fixtures/Student.java", "Student.java"),
                    select("tests/fixtures/extra.zip", "additional-sources.zip"),
                ],
            }
            manifest = {
                "schemaVersion": 1,
                "bookRoot": "tasks",
                "sourceSnapshotHash": "a" * 64,
                "inventoryHash": "b" * 64,
                "projects": [fact],
            }
            archives = []
            for scenario in [
                "reference:correct",
                "reference:correct",
                "contract:extra",
            ]:
                job = jobs.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-extra",
                    scenario,
                    registry=unit_registry(),
                )
                try:
                    self.assertEqual(job["grading"]["sourceFiles"], ["Student.java"])
                    self.assertEqual(
                        job["grading"]["additionalJavaSources"]["maxFiles"], 128
                    )
                    raw = (job.root / "student/additional-sources.zip").read_bytes()
                    self.assertEqual(
                        raw,
                        (
                            job.root
                            / "public-verification/student/additional-sources.zip"
                        ).read_bytes(),
                    )
                    if scenario.startswith("reference"):
                        archives.append(raw)
                        self.assertIn("reference/Base.java", job["sourceHashes"])
                    result = jobs.run_job(job, "host", registry=unit_registry())
                    self.assertEqual(result["classification"], "success", result)
                    self.assertEqual(
                        result["publicResult"]["classification"], "success"
                    )
                    self.assertEqual(
                        result["additionalSources"]["files"][0]["path"], "Base.java"
                    )
                finally:
                    shutil.rmtree(job.root)
            self.assertEqual(archives[0], archives[1])
            saved = fact["check"].pop("additional-java-sources")
            with self.assertRaisesRegex(jobs.JobError, "mapping|Unauthorized"):
                job = jobs.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-extra",
                    "reference:correct",
                    registry=unit_registry(),
                )
                shutil.rmtree(job.root)
            fact["check"]["additional-java-sources"] = saved
            (project / "tests/fixtures/extra.zip").write_bytes(b"tampered")
            with self.assertRaisesRegex(jobs.JobError, "snapshot changed"):
                jobs.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-extra",
                    "contract:extra",
                    registry=unit_registry(),
                )


class PreparationMetadataTests(unittest.TestCase):
    def setUp(self):
        import hashlib

        spec = importlib.util.spec_from_file_location(
            "metadata_jobs", ROOT / "tools/grading_job.py"
        )
        self.jobs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.jobs)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snapshot = Path(self.tmp.name)
        project = self.snapshot / "tasks/p"
        files = {
            "student/Student.java": "public class Student {}",
            "tests/AnswerTest.java": TEST,
        }
        for name, source in files.items():
            path = project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)

        def selected(name, target):
            return {
                "projectRelativePath": name,
                "submissionRelativePath": target,
                "sha256": hashlib.sha256((project / name).read_bytes()).hexdigest(),
            }

        self.feedback = {
            "requirement": "Return the required answer.",
            "what-check": "The answer equals 42.",
        }
        self.cases = [
            {
                "id": "answer",
                "test": "AnswerTest.right",
                "input": "42",
                "expected": "42",
                "name": "Required answer",
            }
        ]
        fact = {
            "qualifiedId": "demo/exr-metadata",
            "projectRoot": "p",
            "check": {
                "runtime": "java25-junit-v1",
                "sourceProfile": {
                    "mode": "implementation",
                    "root": "student",
                    "include": ["*.java"],
                },
                "feedback": self.feedback,
                "public-cases": self.cases,
            },
            "sources": [selected("student/Student.java", "Student.java")],
            "trustedTests": [selected("tests/AnswerTest.java", "AnswerTest.java")],
            "verificationTests": [],
        }
        self.manifest = {
            "schemaVersion": 1,
            "bookRoot": "tasks",
            "sourceSnapshotHash": "a" * 64,
            "inventoryHash": "b" * 64,
            "projects": [fact],
        }

    def prepare(self):
        import shutil

        job = self.jobs.prepare_job(
            self.manifest,
            self.snapshot,
            "demo/exr-metadata",
            "starter",
            registry=unit_registry(),
        )
        self.addCleanup(shutil.rmtree, job.root)
        return job

    def test_prepare_preserves_legal_feedback_and_public_cases(self):
        job = self.prepare()
        expected = {
            "requirement": "Return the required answer.",
            "whatCheck": "The answer equals 42.",
        }
        self.assertEqual(job["grading"]["feedback"], expected)
        self.assertEqual(
            job["grading"]["publicCases"],
            [
                {
                    "id": "answer",
                    "test": "AnswerTest.right",
                    "input": "42",
                    "expected": "42",
                    "name": "Required answer",
                }
            ],
        )
        written = json.loads((job.root / "tests/grading-job.json").read_text())
        self.assertEqual(written["feedback"], expected)
        self.assertEqual(written["publicCases"], job["grading"]["publicCases"])

    def test_embedded_feedback_rejects_malformed_nested_values(self):
        import copy

        job = self.prepare()
        for bad in [
            {"requirement": "", "whatCheck": "Check"},
            {"requirement": "Required", "whatCheck": "Check", "unknown": True},
        ]:
            with self.subTest(feedback=bad):
                value = copy.deepcopy(dict(job))
                value["grading"]["feedback"] = bad
                with self.assertRaises(self.jobs.JobError):
                    self.jobs.validate("grading-job", value)

    def test_embedded_public_cases_rejects_missing_required_and_unknown_fields(self):
        import copy

        job = self.prepare()
        for bad in [
            {
                "id": "answer",
                "test": "AnswerTest.right",
                "input": "42",
                "expected": "42",
            },
            {
                "id": "answer",
                "test": "AnswerTest.right",
                "input": "42",
                "expected": "42",
                "name": "Required answer",
                "unknown": True,
            },
        ]:
            with self.subTest(publicCase=bad):
                value = copy.deepcopy(dict(job))
                value["grading"]["publicCases"] = [bad]
                with self.assertRaises(self.jobs.JobError):
                    self.jobs.validate("grading-job", value)

    def test_prepared_job_keeps_grading_unknown_fields_closed(self):
        import copy

        value = copy.deepcopy(dict(self.prepare()))
        value["grading"]["unknown"] = True
        with self.assertRaises(self.jobs.JobError):
            self.jobs.validate("grading-job", value)
