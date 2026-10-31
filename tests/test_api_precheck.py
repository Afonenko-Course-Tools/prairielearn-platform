"""Порядок API gate проверяется реальными компиляторами и процессами JDK25."""

from gradle_unit_fixtures import registry as unit_registry
import json
import os
from pathlib import Path
import unittest
import hashlib
import importlib.util
import shutil
import test_grading_job as fixtures

grader = fixtures.grader
METHOD = 'api.method("Student","answer",int.class,java.lang.reflect.Modifier.PUBLIC|java.lang.reflect.Modifier.STATIC,0);'


class ApiPrecheckTests(unittest.TestCase):
    run_job = fixtures.JUnitJob.run_job

    def setUp(self):
        fixtures.JUnitJob.setUp(self)
        self.cfg["testFiles"] = ["ApiContract.java", "AnswerTest.java"]
        self.cfg["apiPrecheck"] = {
            "files": ["ApiContract.java"],
            "entry": "ApiContract",
        }
        self.check(METHOD)

    def check(self, body):
        (self.job / "tests/ApiContract.java").write_text(
            "import org.prairielearn.api.PlatformApiPrecheck; public class ApiContract {public static void check(PlatformApiPrecheck.Api api) throws Exception {"
            + body
            + "}}"
        )

    def mismatch(self, source):
        (self.job / "student/Student.java").write_text(source)
        r = self.run_job()
        self.assertEqual(r["classification"], "student-api-mismatch", r)
        self.assertEqual(r["studentCompilation"], "success")
        self.assertEqual(r["trustedCompilation"], "not-run")
        self.assertEqual(r["dependentExecution"], "not-run")
        self.assertEqual(r["apiPrecheck"], "failure")
        self.assertEqual(r["infrastructure"], "complete")
        self.assertTrue(r["gradable"])
        self.assertEqual(r["score"], 0)
        self.assertTrue(r["apiDiagnostic"]["expected"])
        self.assertTrue(r["apiDiagnostic"]["observed"])
        self.assertNotIn("trustedCompilation", r["durations"])
        return r

    def test_missing_class_method_access_static_and_return_stop_dependent_compile(self):
        for source in [
            "class Other {}",
            "public class Student {}",
            "public class Student {static int answer(){return 42;}}",
            "public class Student {public int answer(){return 42;}}",
            "public class Student {public static long answer(){return 42;}}",
        ]:
            with self.subTest(source=source):
                self.mismatch(source)

    def test_correct_api_then_wrong_behavior_is_behavior_failure(self):
        (self.job / "student/Student.java").write_text(
            "public class Student {public static int answer(){return 0;}}"
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "behavior-failure")
        self.assertEqual(r["apiPrecheck"], "success")

    def test_correct_api_runs_original_junit(self):
        r = self.run_job()
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["apiPrecheck"], "success")

    def test_inherited_public_method_is_valid_for_ordinary_client(self):
        self.cfg["sourceFiles"].append("Base.java")
        (self.job / "student/Base.java").write_text(
            "public class Base {public static int answer(){return 42;}}"
        )
        (self.job / "student/Student.java").write_text(
            "public class Student extends Base {}"
        )
        r = self.run_job()
        self.assertEqual(r["classification"], "success")
        self.assertEqual(r["apiPrecheck"], "success")

    def test_declared_here_is_a_separate_explicit_contract_check(self):
        self.cfg["sourceFiles"].append("Base.java")
        (self.job / "student/Base.java").write_text(
            "public class Base {public static int answer(){return 42;}}"
        )
        self.check(
            "var method="
            + METHOD
            + 'api.expect(method.getDeclaringClass()==api.type("Student"),"объявление в Student",method.getDeclaringClass().getName());'
        )
        r = self.mismatch("public class Student extends Base {}")
        self.assertEqual(r["apiDiagnostic"]["expected"], "объявление в Student")

    def test_malformed_student_never_compiles_precheck(self):
        (self.job / "student/Student.java").write_text("not Java")
        (self.job / "tests/ApiContract.java").write_text("also not Java")
        r = self.run_job()
        self.assertEqual(r["classification"], "student-compilation-failure")
        self.assertEqual(r["apiPrecheck"], "not-run")

    def test_trusted_precheck_cannot_statically_reference_student(self):
        self.check("Student.answer();")
        with self.assertRaisesRegex(
            grader.GraderError, "API precheck compilation failed"
        ):
            self.run_job()

    def test_trusted_test_defect_after_precheck_stays_infrastructure(self):
        (self.job / "tests/AnswerTest.java").write_text("broken trusted Java")
        result = self.run_job()
        self.assertEqual(result["classification"], "infrastructure-failure")
        self.assertFalse(result["gradable"])
        self.assertTrue(result["grading_error"])
        self.assertNotIn("score", result)
        self.assertEqual(
            (
                result["studentCompilation"],
                result["trustedCompilation"],
                result["dependentExecution"],
            ),
            ("success", "failure", "not-run"),
        )
        self.assertIn("apiExecution", result["durations"])

    def test_metadata_does_not_initialize_student(self):
        self.check(
            METHOD
            + 'api.expect(System.getProperty("api.probe.initialized")==null,"без инициализации","инициализирован");'
        )
        (self.job / "student/Student.java").write_text(
            'public class Student {static {System.setProperty("api.probe.initialized","yes");}public static int answer(){return 42;}}'
        )
        self.assertEqual(self.run_job()["score"], 1)

    def test_typed_positive_client_rejects_extra_checked_throws(self):
        self.check(
            METHOD
            + 'api.compiles("Client","class Client {int call(){return Student.answer();}}",true);'
        )
        self.mismatch(
            "public class Student {public static int answer() throws java.io.IOException {return 42;}}"
        )

    def test_typed_generic_client_detects_erased_return_mismatch(self):
        self.check(
            'api.method("Student","names",java.util.List.class,9,0);api.compiles("Client","class Client {java.util.List<String> values=Student.names();}",true);'
        )
        self.mismatch(
            "public class Student {public static java.util.List<Object> names(){return java.util.List.of();}}"
        )

    def test_positive_and_negative_clients_before_behavior(self):
        self.check(
            METHOD
            + 'api.compiles("Good","class Good {int value=Student.answer();}",true);api.compiles("Bad","class Bad {String value=Student.answer();}",false);'
        )
        self.assertEqual(self.run_job()["score"], 1)

    def test_precheck_timeout_is_infrastructure(self):
        self.cfg["limits"]["run-seconds"] = 0.5
        self.check("while(true){}")
        with self.assertRaisesRegex(grader.GraderError, "API precheck.*timeout"):
            self.run_job()

    def test_precheck_output_overflow_is_infrastructure(self):
        self.cfg["limits"]["max-output-bytes"] = 1024
        self.check('while(true){System.out.println("x".repeat(1024));}')
        with self.assertRaisesRegex(grader.GraderError, "API precheck.*output_limit"):
            self.run_job()

    def test_invalid_precheck_subset_and_paths_fail_closed(self):
        for config in [
            {"files": ["Missing.java"], "entry": "ApiContract"},
            {"files": ["../ApiContract.java"], "entry": "ApiContract"},
            {"files": ["ApiContract.java"], "entry": "../Evil"},
            {"files": ["ApiContract.java", "AnswerTest.java"], "entry": "ApiContract"},
        ]:
            with self.subTest(config=config):
                self.cfg["apiPrecheck"] = config
                with self.assertRaises(grader.GraderError):
                    self.run_job()


@unittest.skipUnless(
    os.environ.get("PL_API_TEST_IMAGE"),
    "Set PL_API_TEST_IMAGE to the local API candidate",
)
class ApiContainerTests(ApiPrecheckTests):
    def run_job(self):
        import subprocess

        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        p = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--cpus",
                "0.9",
                "--memory",
                "512m",
                "--mount",
                f"type=bind,src={self.job},dst=/grade",
                os.environ["PL_API_TEST_IMAGE"],
                "--verification",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        r = json.loads((self.job / "results/results.json").read_text())
        if r.get("infrastructure") == "failure":
            self.assertEqual(p.returncode, 2, p.stderr)
            if (
                r.get("classification"),
                r.get("studentCompilation"),
                r.get("trustedCompilation"),
                r.get("dependentExecution"),
            ) == ("infrastructure-failure", "success", "failure", "not-run"):
                return r
            raise grader.GraderError(
                r.get("message", "container infrastructure failed")
            )
        self.assertEqual(p.returncode, 0, p.stderr)
        return r

    def test_precheck_official_sandbox_cannot_read_proc_or_write_trusted(self):
        self.check(
            METHOD
            + """try{java.nio.file.Files.readString(java.nio.file.Path.of("/proc/self/maps"));throw new AssertionError("proc readable");}catch(java.nio.file.AccessDeniedException expected){}
  try{java.nio.file.Files.writeString(java.nio.file.Path.of("/grade/tests/changed"),"x");throw new AssertionError("tests writable");}catch(java.nio.file.AccessDeniedException expected){}"""
        )
        r = self.run_job()
        self.assertEqual(r["score"], 1)
        self.assertEqual(r["apiContainment"], "official-landlock-sbuser")


class ApiDeliveryTests(unittest.TestCase):
    def test_api_precheck_cannot_be_declared_on_fish(self):
        root = Path(__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "api_jobs", root / "tools/grading_job.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with self.assertRaises(m.JobError):
            m.validate_profile(
                {
                    "runtime": "fish-git-v1",
                    "api-precheck": {"files": ["Api.java"], "entry": "Api"},
                }
            )

    def test_result_cannot_claim_success_with_failed_api_stage(self):
        import test_review_receipts as review

        root = Path(__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "api_jobs", root / "tools/grading_job.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        value = review.result()
        value["apiPrecheck"] = "failure"
        with self.assertRaises(m.JobError):
            m.validate("check-result", value)

    def test_prepare_maps_private_public_prechecks_and_validates_mismatch_result(self):
        import tempfile
        import sys
        from unittest.mock import patch

        root = Path(__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "api_jobs", root / "tools/grading_job.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        # Загруженный по пути tool получает тот же sibling search path, что и CLI.
        with patch.object(sys, "path", [str(root / "tools"), *sys.path]), tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            p = snapshot / "tasks/p"
            files = {
                "student/Student.java": "public class Student {}",
                "tests/ApiContract.java": 'import org.prairielearn.api.PlatformApiPrecheck; public class ApiContract {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.type("Missing");}}',
                "tests/AnswerTest.java": fixtures.TEST,
                "student/public/PublicApi.java": 'import org.prairielearn.api.PlatformApiPrecheck; public class PublicApi {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.type("Missing");}}',
                "student/public/PublicTest.java": "import org.junit.jupiter.api.Test; public class PublicTest {@Test void okay(){}}",
            }
            for name, source in files.items():
                path = p / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)

            def s(name, target):
                return {
                    "projectRelativePath": name,
                    "submissionRelativePath": target,
                    "sha256": hashlib.sha256((p / name).read_bytes()).hexdigest(),
                }

            fact = {
                "qualifiedId": "demo/exr-api",
                "projectRoot": "p",
                "check": {
                    "runtime": "java25-junit-v1",
                    "api-precheck": {
                        "files": ["tests/ApiContract.java"],
                        "entry": "ApiContract",
                    },
                    "verification-api-precheck": {
                        "files": ["student/public/PublicApi.java"],
                        "entry": "PublicApi",
                    },
                },
                "sources": [s("student/Student.java", "Student.java")],
                "trustedTests": [
                    s("tests/ApiContract.java", "ApiContract.java"),
                    s("tests/AnswerTest.java", "AnswerTest.java"),
                ],
                "verificationTests": [
                    s("student/public/PublicApi.java", "public/PublicApi.java"),
                    s("student/public/PublicTest.java", "public/PublicTest.java"),
                ],
                "apiPrecheck": {"files": ["ApiContract.java"], "entry": "ApiContract"},
                "verificationApiPrecheck": {
                    "files": ["public/PublicApi.java"],
                    "entry": "PublicApi",
                },
            }
            manifest = {
                "schemaVersion": 1,
                "bookRoot": "tasks",
                "sourceSnapshotHash": "a" * 64,
                "inventoryHash": "b" * 64,
                "projects": [fact],
            }
            job = m.prepare_job(
                manifest, snapshot, "demo/exr-api", "starter", registry=unit_registry()
            )
            try:
                self.assertEqual(
                    job["grading"]["apiPrecheck"],
                    {"files": ["ApiContract.java"], "entry": "ApiContract"},
                )
                public = json.loads(
                    (
                        job.root / "public-verification/tests/grading-job.json"
                    ).read_text()
                )
                self.assertEqual(
                    public["apiPrecheck"],
                    {"files": ["public/PublicApi.java"], "entry": "PublicApi"},
                )
                saved_public = fact.pop("verificationApiPrecheck")
                saved_declaration = fact["check"].pop("verification-api-precheck")
                try:
                    with self.assertRaises(m.JobError):
                        omitted = m.prepare_job(
                            manifest,
                            snapshot,
                            "demo/exr-api",
                            "starter",
                            registry=unit_registry(),
                        )
                        shutil.rmtree(omitted.root)
                finally:
                    fact["verificationApiPrecheck"] = saved_public
                    fact["check"]["verification-api-precheck"] = saved_declaration
                result = m.run_job(job, "host", registry=unit_registry())
                self.assertEqual(result["classification"], "student-api-mismatch")
                m.validate("check-result", result)
                self.assertEqual(
                    result["publicResult"]["classification"], "student-api-mismatch"
                )
                wrong = {**result, "score": 1}
                with self.assertRaises(m.JobError):
                    m.validate("check-result", wrong)
                # Native delivery binds API descriptor and source bytes exactly like JUnit.
                native = snapshot / "native"
                question = native / "questions/demo/exr-api"
                question.mkdir(parents=True)
                image = unit_registry()["profiles"]["java25-junit-v1"]["image"]
                (question / "info.json").write_text(
                    json.dumps({"externalGradingOptions": {"image": image}})
                )
                shutil.copytree(job.root / "tests", question / "tests")
                shutil.copytree(
                    job.root / "student", question / "serverFilesQuestion/starter"
                )
                native_files = {
                    f.relative_to(native)
                    .as_posix(): hashlib.sha256(f.read_bytes())
                    .hexdigest()
                    for f in native.rglob("*")
                    if f.is_file()
                }
                delivery = {
                    "schemaVersion": 3,
                    "courseId": "demo",
                    "bookRoot": "tasks",
                    "works": [{"id": "sec-api"}],
                    "instances": {"unit": {"works": ["sec-api"]}},
                    "gradingPayloads": {
                        "demo/exr-api": {
                            "uuid": "00000000-0000-4000-8000-000000000001",
                            "grading": {"method": "external"},
                            "submission": {"mode": "upload"},
                            "sourceRoot": fact["projectRoot"],
                            "projectCheck": "unit-api",
                            "runtime": fact["check"]["runtime"],
                            "sources": fact["sources"],
                        }
                    },
                    "sourceSnapshotHash": "a" * 64,
                    "inventoryHash": "b" * 64,
                    "questions": ["demo/exr-api"],
                    "verificationInventoryHash": m.digest(
                        m.scenario_inventory(manifest, snapshot)
                    ),
                    "files": native_files,
                }
                delivery["deliveryHash"] = m.digest(delivery)
                delivery["_root"] = str(native)
                delivered = m.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-api",
                    "starter",
                    scope="delivery",
                    delivery=delivery,
                    registry=unit_registry(),
                )
                try:
                    self.assertEqual(
                        delivered["grading"]["apiPrecheck"],
                        {"files": ["ApiContract.java"], "entry": "ApiContract"},
                    )
                finally:
                    shutil.rmtree(delivered.root)
                cfg = question / "tests/grading-job.json"
                bad = json.loads(cfg.read_text())
                bad["apiPrecheck"]["entry"] = "Wrong"
                cfg.write_text(json.dumps(bad))
                with self.assertRaises(m.JobError):
                    m.prepare_job(
                        manifest,
                        snapshot,
                        "demo/exr-api",
                        "starter",
                        scope="delivery",
                        delivery=delivery,
                        registry=unit_registry(),
                    )
            finally:
                shutil.rmtree(job.root)
            fact["apiPrecheck"]["files"] = ["public/PublicApi.java"]
            with self.assertRaises(m.JobError):
                m.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-api",
                    "starter",
                    registry=unit_registry(),
                )
            fact["apiPrecheck"]["files"] = ["ApiContract.java"]
            (p / "tests/ApiContract.java").write_text("tampered")
            with self.assertRaises(m.JobError):
                m.prepare_job(
                    manifest,
                    snapshot,
                    "demo/exr-api",
                    "starter",
                    registry=unit_registry(),
                )
