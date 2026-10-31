"""Обычный library JAR: schema/mapping и настоящий trusted recipe на host.

Host recipe/Jupiter controls не квалифицируют native supervisor или OCI image.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile

import test_assertion_feedback as af
import test_gradle_build as native
from gradle_unit_fixtures import registry

ROOT = native.ROOT
jobs = native.BuildEvidenceTests().jobs()


def library(config):
    return dict(
        config,
        runtime="java25-gradle-junit-v1",
        javaBuild={"kind": "gradle-jar-v1", "artifact": "books.jar"},
    )


class LibraryContract(unittest.TestCase):
    setUp = native.fixtures.JUnitJob.setUp

    def test_closed_library_descriptor_and_public_profile(self):
        config = library(self.cfg)
        check = {
            "runtime": config["runtime"],
            "sourceProfile": {
                "mode": "implementation",
                "root": "student",
                "include": ["*.java"],
            },
            "java-build": {"kind": "gradle-jar-v1", "artifact": "books.jar"},
        }
        for name, validate in (
            ("runtime", lambda: native.grader.validate_config(config)),
            ("descriptor", lambda: jobs.validate("grading-descriptor", config)),
            ("project-check", lambda: jobs.validate_profile(check)),
        ):
            with self.subTest(boundary=name):
                validate()
        self.assertNotIn("mainClass", config["javaBuild"])
        self.assertNotIn("main-class", check["java-build"])

    def test_present_invalid_main_is_not_omission(self):
        for value in (None, "", " ", False, 0, [], {}, "a/b", "a..Main", "Main\n"):
            config = library(self.cfg)
            config["javaBuild"]["mainClass"] = value
            check = {
                "runtime": config["runtime"],
                "sourceProfile": {
                    "mode": "implementation",
                    "root": "student",
                    "include": ["*.java"],
                },
                "java-build": {
                    "kind": "gradle-jar-v1",
                    "artifact": "books.jar",
                    "main-class": value,
                },
            }
            with self.subTest(value=value):
                with self.assertRaises(native.grader.GraderError):
                    native.grader.validate_config(config)
                with self.assertRaises(jobs.JobError):
                    jobs.validate("grading-descriptor", config)
                with self.assertRaises(jobs.JobError):
                    jobs.validate_profile(check)
        for field, value in (
            ("extra", True),
            ("kind", "arbitrary"),
            ("artifact", "../books.jar"),
        ):
            config = library(self.cfg)
            config["javaBuild"][field] = value
            with self.subTest(field=field), self.assertRaises(
                native.grader.GraderError
            ):
                native.grader.validate_config(config)

    def test_prepare_omits_main_instead_of_guessing_and_binds_input(self):
        root = self.job
        project = root / "tasks/p"
        project.mkdir(parents=True)
        content = {
            "student/Student.java": "class Student {}",
            "tests/T.java": "class T {}",
        }
        selected = {}
        for name, text in content.items():
            p = project / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            selected[name] = {
                "projectRelativePath": name,
                "submissionRelativePath": p.name,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        check = {
            "runtime": "java25-gradle-junit-v1",
            "sourceProfile": {
                "mode": "implementation",
                "root": "student",
                "include": ["*.java"],
            },
            "java-build": {"kind": "gradle-jar-v1", "artifact": "books.jar"},
        }
        p = {
            "qualifiedId": "synthetic/library",
            "projectRoot": "p",
            "check": check,
            "sources": [selected["student/Student.java"]],
            "trustedTests": [selected["tests/T.java"]],
        }
        manifest = {
            "schemaVersion": 1,
            "bookRoot": "tasks",
            "sourceSnapshotHash": "a" * 64,
            "inventoryHash": "b" * 64,
            "projects": [p],
        }
        job = jobs.prepare_job(
            manifest, root, p["qualifiedId"], "starter", registry=registry()
        )
        self.addCleanup(shutil.rmtree, job.root)
        jobs.validate("grading-job", job)
        expected = {"kind": "gradle-jar-v1", "artifact": "books.jar"}
        self.assertEqual(job["grading"]["javaBuild"], expected)
        self.assertEqual(
            json.loads((job.root / "tests/grading-job.json").read_text())["javaBuild"],
            expected,
        )
        native.grader.validate_config(job["grading"])
        for value in (None, "", False, "Main\n"):
            bad = copy.deepcopy(dict(job))
            bad["grading"]["javaBuild"]["mainClass"] = value
            with self.subTest(jobMain=value), self.assertRaises(jobs.JobError):
                jobs.validate("grading-job", bad)
        digest = jobs._prepared_build_input_hash(job)
        self.assertEqual(
            digest,
            jobs.digest(
                {
                    "sources": {
                        "Student.java": selected["student/Student.java"]["sha256"]
                    },
                    "javaBuild": expected,
                }
            ),
        )
        executable = dict(expected, mainClass="Student")
        self.assertNotEqual(
            digest,
            jobs.digest(
                {
                    "sources": {
                        "Student.java": selected["student/Student.java"]["sha256"]
                    },
                    "javaBuild": executable,
                }
            ),
        )


class LibraryGateOrder(af.ProductionCase):
    def test_library_compile_api_zero_and_uncontained_build_is_infrastructure(self):
        self.cfg = library(self.cfg)
        self.cfg["apiPrecheck"] = {
            "files": ["ApiContract.java"],
            "entry": "ApiContract",
        }
        self.cfg["testFiles"].append("ApiContract.java")
        (self.job / "tests/ApiContract.java").write_text(
            'import org.prairielearn.api.PlatformApiPrecheck;public class ApiContract {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.method("Student","answer",int.class,9,0);}}'
        )
        for source, classification in (
            ("not Java", "student-compilation-failure"),
            ("public class Student {}", "student-api-mismatch"),
            (
                "public class Student {public static int answer(){return 42;}}",
                "infrastructure-failure",
            ),
        ):
            with self.subTest(classification=classification):
                (self.job / "student/Student.java").write_text(source)
                result = self.run_job()
                self.assertEqual(result["classification"], classification)
                if classification == "infrastructure-failure":
                    self.assertFalse(result["gradable"])
                    self.assertNotIn("score", result)
                    self.assertIn("apiExecution", result["durations"])
                    self.assertEqual(result["dependentExecution"], "not-run")
                    self.assertEqual(result["buildEvidence"]["status"], "failure")
                    self.assertIn("containment", result["message"])
                else:
                    self.assertEqual(result["score"], 0)
                    self.assertEqual(result["buildEvidence"]["status"], "not-run")
                self.assertNotIn("counts", result)
                self.assertNotIn("gradleBuild", result["durations"])
                destination = os.environ.get("LIBRARY_RECIPE_RECEIPTS")
                if destination:
                    out = Path(destination)
                    out.mkdir(mode=0o700, parents=True, exist_ok=True)
                    (out / ("gate-" + classification + ".json")).write_text(
                        json.dumps(
                            {
                                "config": self.cfg,
                                "sourceSha256": hashlib.sha256(
                                    source.encode()
                                ).hexdigest(),
                                "result": result,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n"
                    )


class ActualTrustedRecipe(unittest.TestCase):
    def setUp(self):
        source = os.environ.get("JAVA_ACCEPTED_SNAPSHOT")
        if not source:
            self.skipTest("JAVA_ACCEPTED_SNAPSHOT задаёт immutable D1 archive")
        self.source = Path(source)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.calls = []
        self.artifacts = {}
        self.receipts = (
            Path(os.environ["LIBRARY_RECIPE_RECEIPTS"])
            if os.environ.get("LIBRARY_RECIPE_RECEIPTS")
            else None
        )
        if self.receipts:
            self.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.addCleanup(self.save)

    def preserve(self, name, path):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        self.artifacts[name] = {"sha256": digest, "bytes": len(data)}
        if self.receipts:
            blobs = self.receipts / "generated"
            blobs.mkdir(mode=0o700, exist_ok=True)
            out = blobs / digest
            if not out.exists():
                out.write_bytes(data)
                out.chmod(0o600)
        return digest

    def save(self):
        if self.receipts:
            (self.receipts / (self._testMethodName + ".json")).write_text(
                json.dumps(
                    {
                        "mode": "HOST_DIAGNOSTIC_NOT_NATIVE_OR_OCI_ADMISSION",
                        "calls": self.calls,
                        "artifacts": self.artifacts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )

    def run_process(self, argv, cwd=None, input=None):
        home = self.work / "home"
        home.mkdir(exist_ok=True)
        env = {
            key: os.environ[key]
            for key in ("JAVA_HOME", "XDG_CACHE_HOME", "GRADLE_USER_HOME")
        }
        env.update(
            PATH=os.environ["JAVA_HOME"] + "/bin:/usr/bin:/bin",
            HOME=str(home),
            LANG="C.UTF-8",
            LC_ALL="C.UTF-8",
        )
        start = time.monotonic()
        p = subprocess.Popen(
            list(map(str, argv)),
            cwd=cwd or self.work,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            output, _ = p.communicate(input, timeout=40)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(p.pid, signal.SIGKILL)
            output, _ = p.communicate(timeout=5)
        log = self.work / f"process-{len(self.calls)}.log"
        log.write_text(output)
        self.preserve(log.name, log)
        self.calls.append(
            {
                "argv": list(map(str, argv)),
                "cwd": str(cwd or self.work),
                "env": env,
                "seconds": time.monotonic() - start,
                "exitCode": p.returncode,
                "timeout": timed_out,
                "terminal": True,
                "outputSha256": hashlib.sha256(output.encode()).hexdigest(),
            }
        )
        self.assertFalse(timed_out, output)
        self.assertEqual(p.returncode, 0, output)
        return output

    def build(self, relative, filename, main=None):
        unit = self.work / "project"
        unit.mkdir()
        (unit / "src").mkdir()
        self.preserve("selected/" + filename, self.source / relative)
        shutil.copyfile(self.source / relative, unit / "src" / filename)
        config = {"kind": "gradle-jar-v1", "artifact": "production.jar"}
        if main is not None:
            config["mainClass"] = main
        (unit / "native-config.json").write_text(json.dumps(config, sort_keys=True))
        for name in ("build.gradle", "settings.gradle"):
            shutil.copyfile(ROOT / "runtime/gradle-jar-v1" / name, unit / name)
            self.preserve("recipe/" + name, unit / name)
        (unit / "gradle.properties").write_text(
            "org.gradle.java.installations.auto-download=false\norg.gradle.java.installations.auto-detect=false\norg.gradle.java.installations.paths="
            + os.environ["JAVA_HOME"]
            + "\norg.gradle.daemon=false\norg.gradle.workers.max=2\norg.gradle.jvmargs=-Xmx128m -XX:ActiveProcessorCount=2 -XX:-UsePerfData\n"
        )
        self.preserve("descriptor", unit / "native-config.json")
        self.preserve("gradle.properties", unit / "gradle.properties")
        (unit / "not-selected").mkdir()
        (unit / "not-selected/Rejected.java").write_text("not Java")
        (unit / "tests").mkdir()
        (unit / "tests/TrustedTest.java").write_text(
            "not Java: trusted checks must not join production"
        )
        command = [
            os.environ.get("HOST_GRADLE", "/usr/bin/gradle"),
            "--offline",
            "--no-daemon",
            "--no-build-cache",
            "--console=plain",
            "--project-cache-dir",
            str(unit / "project-cache"),
            "clean",
            "jar",
        ]
        output = self.run_process(command, unit)
        self.assertNotIn(":test", output)
        self.assertFalse((unit / "build/classes/java/test").exists())
        jar = unit / "build/libs/production.jar"
        self.preserve("production.jar", jar)
        state = native.grader._artifact_state(unit, "build/libs/production.jar")
        with zipfile.ZipFile(jar) as archive:
            self.assertEqual(
                sorted(n for n in archive.namelist() if n.endswith(".class")),
                [filename[:-5] + ".class"],
            )
            manifest = archive.read("META-INF/MANIFEST.MF").decode()
        return unit, jar, manifest, state

    def test_book_library_jar_without_main_and_genuine_junit(self):
        unit, jar, manifest, before = self.build(
            "tasks/projects/objects/book-selection/reference/src/main/java/Book.java",
            "Book.java",
        )
        self.assertNotIn("Main-Class:", manifest)
        self.assertEqual(
            json.loads((unit / "native-config.json").read_text()),
            {"kind": "gradle-jar-v1", "artifact": "production.jar"},
        )
        tests = self.work / "junit-tests"
        tests.mkdir()
        source = (
            self.source
            / "tasks/projects/objects/book-selection/checks/src/test/java/BookSelectionTest.java"
        )
        self.preserve("trusted/BookSelectionTest.java", source)
        junit = (
            ROOT
            / "runtime/java25-junit-v1/junit-platform-console-standalone-1.14.1.jar"
        )
        self.preserve("pinned-junit.jar", junit)
        self.run_process(
            [
                Path(os.environ["JAVA_HOME"]) / "bin/javac",
                "--release",
                "25",
                "-proc:none",
                "-cp",
                os.pathsep.join(map(str, (jar, junit))),
                "-d",
                tests,
                source,
            ]
        )
        reports = self.work / "junit-reports"
        self.run_process(
            [
                Path(os.environ["JAVA_HOME"]) / "bin/java",
                "--illegal-native-access=deny",
                "-jar",
                junit,
                "execute",
                "--class-path",
                os.pathsep.join(map(str, (jar, tests))),
                "--select-class",
                "BookSelectionTest",
                "--disable-banner",
                "--details=summary",
                "--reports-dir",
                reports,
            ]
        )
        report = reports / "TEST-junit-jupiter.xml"
        self.preserve("genuine-junit.xml", report)
        suite = ET.parse(report).getroot()
        self.assertEqual(
            (suite.get("tests"), suite.get("failures"), suite.get("errors")),
            ("23", "0", "0"),
        )
        self.assertEqual(
            native.grader._artifact_state(unit, "build/libs/production.jar"), before
        )

    def test_existing_executable_keeps_main_manifest_and_launch(self):
        unit, jar, manifest, before = self.build(
            "tasks/projects/arrays/reverse-array/reference/src/main/java/Main.java",
            "Main.java",
            "Main",
        )
        self.assertIn("Main-Class: Main", manifest)
        output = self.run_process(
            [
                Path(os.environ["JAVA_HOME"]) / "bin/java",
                "--illegal-native-access=deny",
                "-jar",
                jar,
            ],
            input="4 7 -2 7 0\n",
        )
        self.assertEqual(output.split(), ["0", "7", "-2", "7"])
        self.assertEqual(
            native.grader._artifact_state(unit, "build/libs/production.jar"), before
        )


if __name__ == "__main__":
    unittest.main()
