"""Проверка immutable образа с настоящими Gradle/JUnit и ролями."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from json_boundary import JSONObject, json_object
from grading_types import JavaGradingDescriptor
import test_plain_runtime as fixtures


@unittest.skipUnless(os.environ.get("PL_TEST_IMAGE"), "Нужен собранный PL_TEST_IMAGE")
class PlainImageTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = fixtures.PlainRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.job: Path = fixture.job
        self.config: JavaGradingDescriptor = fixture.config

    def invoke(
        self, cpus: str = "2", *, verification: bool = True
    ) -> tuple[subprocess.CompletedProcess[str], JSONObject]:
        image = os.environ["PL_TEST_IMAGE"]
        if re.fullmatch(r"(?:sha256:|[^\s]+@sha256:)[0-9a-f]{64}", image) is None:
            self.fail(
                "PL_TEST_IMAGE должен быть immutable OCI digest или локальным image ID"
            )
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.config))
        # Только временный mount этой проверки возвращается владельцу перед cleanup.
        self.addCleanup(
            subprocess.run,
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint",
                "/bin/chown",
                "--mount",
                f"type=bind,src={self.job},dst=/grade",
                image,
                "-Rh",
                f"{os.getuid()}:{os.getgid()}",
                "/grade",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        command = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--cpus=" + cpus,
            "--memory=512m",
            "--pids-limit=128",
            "--mount",
            f"type=bind,src={self.job},dst=/grade",
            image,
        ]
        if verification:
            command.append("--verification")
        result = subprocess.run(command, capture_output=True, text=True, timeout=35)
        payload = json_object(
            json.loads((self.job / "results/results.json").read_text())
        )
        return result, payload

    def test_native_gradle_jar_and_junit(self) -> None:
        self.config.update(
            runtime="java25-gradle-junit-v1",
            javaBuild={"kind": "gradle-jar-v1", "artifact": "answer.jar"},
        )
        limits = self.config["limits"]
        limits.update({"compile-seconds": 20, "outer-seconds": 35})
        self.config["limits"] = limits
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["score"], 1)
        self.assertEqual(payload["containment"], "official-landlock-sbuser")
        build = json_object(payload["buildEvidence"])
        self.assertEqual(build["status"], "success")
        self.assertTrue((self.job / "build/libs/answer.jar").is_file())
        self.assertNotIn("executionEvidence", payload)
        self.assertNotIn("sha256", json_object(build["artifact"]))

    def test_native_junit_temporary_files_and_entropy_fit_original_execution_limit(
        self,
    ) -> None:
        self.config.update(
            runtime="java25-gradle-junit-v1",
            javaBuild={"kind": "gradle-jar-v1", "artifact": "answer.jar"},
        )
        limits = self.config["limits"]
        limits.update({"compile-seconds": 120, "outer-seconds": 300, "run-seconds": 10})
        self.config["limits"] = limits
        (self.job / "tests/AnswerTest.java").write_text("""
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.SecureRandom;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
    @TempDir Path directory;
    @Test void ordinaryJdkTemporaryFilesAndEntropy() throws Exception {
        Path file = Files.createTempFile(directory, "fictional-", ".txt");
        Files.writeString(file, "42");
        assertEquals("42", Files.readString(file));
        assertEquals(64, new SecureRandom().generateSeed(64).length);
        assertEquals(42, Student.answer());
    }
}
""")
        result, payload = self.invoke(cpus="0.9")
        self.assertEqual(result.returncode, 0, payload.get("message", result.stderr))
        self.assertEqual(payload["classification"], "success")
        self.assertEqual(json_object(payload["counts"])["passed"], 1)
        execution = json_object(payload["durations"])["execution"]
        assert isinstance(execution, (int, float)) and not isinstance(execution, bool)
        self.assertLess(execution, 10)
        self.assertEqual(payload["containment"], "official-landlock-sbuser")

    @unittest.skipUnless(
        os.environ.get("JAVA_CONSOLE_SUPPORT"),
        "Нужен канонический JAVA_CONSOLE_SUPPORT",
    )
    def test_nested_common_launcher_circle_fits_original_execution_limit(self) -> None:
        self.config.update(
            runtime="java25-gradle-junit-v1",
            javaBuild={"kind": "gradle-jar-v1", "artifact": "answer.jar"},
        )
        limits = self.config["limits"]
        limits.update({"compile-seconds": 120, "outer-seconds": 300, "run-seconds": 10})
        self.config["limits"] = limits
        self.config["sourceFiles"] = ["Circle.java"]
        self.config["testFiles"] = ["AnswerTest.java", "coursesupport/JavaProcess.java"]
        (self.job / "student/Student.java").unlink()
        (self.job / "student/Circle.java").write_text("""
public class Circle {
    public static void main(String[] args) {
        double radius = Double.parseDouble(args[0]);
        System.out.print(Math.PI * radius * radius);
    }
}
""")
        helper = self.job / "tests/coursesupport/JavaProcess.java"
        helper.parent.mkdir()
        shutil.copyfile(os.environ["JAVA_CONSOLE_SUPPORT"], helper)
        (self.job / "tests/AnswerTest.java").write_text("""
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
    @ParameterizedTest(name="Площадь круга радиуса {0}")
    @ValueSource(doubles={0, 1, 2, 3, 0.5, 10})
    void circle(double radius) throws Exception {
        var result = coursesupport.JavaProcess.runCheckingUncaught(
            Class.forName("Circle"), "", Double.toString(radius));
        assertEquals(0, result.exitCode());
        assertEquals(Math.PI * radius * radius,
            Double.parseDouble(result.stdout().strip()), 1e-9);
    }
}
""")
        result, payload = self.invoke(cpus="0.9")
        self.assertEqual(result.returncode, 0, payload.get("message", result.stderr))
        self.assertEqual(payload["classification"], "success")
        self.assertEqual(payload["score"], 1)
        self.assertEqual(json_object(payload["counts"])["passed"], 6)
        execution = json_object(payload["durations"])["execution"]
        assert isinstance(execution, (int, float)) and not isinstance(execution, bool)
        self.assertLess(execution, 10)
        self.assertEqual(payload["containment"], "official-landlock-sbuser")

    def test_broken_trusted_suite_has_no_score(self) -> None:
        (self.job / "tests/AnswerTest.java").write_text("not java")
        result, payload = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["classification"], "infrastructure-failure")
        self.assertNotIn("score", payload)

    def test_ordinary_native_worker_delivers_private_safe_infrastructure_failure(
        self,
    ) -> None:
        (self.job / "tests/AnswerTest.java").write_text(
            "public class PRIVATE_TOOL_CANARY { PRIVATE_SOURCE_CANARY }"
        )
        result, payload = self.invoke(cpus="0.9", verification=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(payload["gradable"], False)
        self.assertIs(payload["grading_error"], True)
        self.assertEqual(payload["classification"], "infrastructure-failure")
        self.assertNotIn("score", payload)
        self.assertEqual(json_object(payload["feedback"])["kind"], "infrastructure")
        message = payload["message"]
        assert isinstance(message, str)
        self.assertIn("Проверка недоступна", message)
        self.assertNotIn(
            "PRIVATE_", json.dumps(payload) + result.stdout + result.stderr
        )
