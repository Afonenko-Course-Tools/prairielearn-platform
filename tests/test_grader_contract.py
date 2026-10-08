"""Real Java fixtures catch incorrect grading, containment and process limits."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

GRADER = Path(os.environ.get(
    "GRADER_SCRIPT", str(Path(__file__).resolve().parents[1] / "images/java25-grader/grade.py")
))
CHECKS = """public class Checks {
  public static void main(String[] args) {
    if (Runtime.version().feature() != 25) System.exit(2);
    if (Student.answer() != 42) System.exit(1);
  }
}
"""


class GraderContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pl-grader-")
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name)
        (self.job / "student").mkdir()
        (self.job / "tests").mkdir()
        self.source("return 42;")
        (self.job / "tests/Checks.java").write_text(CHECKS)
        self.config = {
            "sourceFiles": ["Student.java"],
            "testFiles": ["Checks.java"],
            "mainClass": "Checks",
            "runTimeoutSeconds": 1,
            "requiredMethods": [{"className":"Student","methodName":"answer", "descriptor":"()I","static":True}],
        }
        self.write_config()

    def source(self, body):
        (self.job / "student/Student.java").write_text(
            "public class Student { public static int answer() { " + body + " } }"
        )

    def write_config(self):
        (self.job / "tests/grading.json").write_text(json.dumps(self.config))

    def grader(self):
        self.assertTrue(GRADER.is_file(), "Java25 grader implementation is missing")
        spec = importlib.util.spec_from_file_location("java25_grader", GRADER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_correct_answer_gets_full_score_on_actual_java25(self):
        self.assertEqual(self.grader().grade(self.job)["score"], 1)

    def test_failed_checks_get_zero_score(self):
        self.source("return 41;")
        self.assertEqual(self.grader().grade(self.job)["score"], 0)

    def test_premature_student_exit_cannot_receive_full_credit(self):
        self.source("System.exit(0); return 0;")
        self.assertEqual(self.grader().grade(self.job)["score"], 0)

    def test_missing_student_method_is_invalid_not_harness_failure(self):
        (self.job / "student/Student.java").write_text("public class Student { public static int different() { return 42; } }")
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_wrong_student_return_type_is_invalid(self):
        (self.job / "student/Student.java").write_text('public class Student { public static String answer() { return "42"; } }')
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_nonstatic_student_method_is_invalid(self):
        (self.job / "student/Student.java").write_text("public class Student { public int answer() { return 42; } }")
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_broken_harness_remains_an_instructor_failure(self):
        (self.job / "tests/Checks.java").write_text("public class Checks { this is not Java; }")
        module=self.grader()
        with self.assertRaises(module.GraderError): module.grade(self.job)

    def test_malformed_api_contract_is_configuration_error(self):
        self.config["requiredMethods"][0]["descriptor"]="not-a-jvm-descriptor"
        self.write_config();module=self.grader()
        with self.assertRaises(module.GraderError): module.grade(self.job)

    def test_missing_api_contract_is_configuration_error(self):
        self.config.pop("requiredMethods");self.write_config();module=self.grader()
        with self.assertRaises(module.GraderError): module.grade(self.job)

    def test_compile_error_is_not_gradable(self):
        self.source("this is not java;")
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_missing_submission_is_not_gradable(self):
        (self.job / "student/Student.java").unlink()
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_additional_unlisted_submission_is_not_compiled(self):
        (self.job / "student/Unexpected.java").write_text("broken java")
        self.assertEqual(self.grader().grade(self.job)["score"], 1)

    def test_source_traversal_is_configuration_error(self):
        self.config["sourceFiles"] = ["../tests/Checks.java"]
        self.write_config()
        module = self.grader()
        with self.assertRaises(module.GraderError):
            module.grade(self.job)

    def test_source_symlink_is_not_gradable(self):
        source = self.job / "student/Student.java"
        text = source.read_text()
        source.unlink()
        other = self.job / "other.java"
        other.write_text(text)
        source.symlink_to(other)
        self.assertFalse(self.grader().grade(self.job)["gradable"])

    def test_missing_harness_is_configuration_error(self):
        (self.job / "tests/Checks.java").unlink()
        module = self.grader()
        with self.assertRaises(module.GraderError):
            module.grade(self.job)

    def test_empty_harness_is_configuration_error(self):
        self.config["testFiles"] = []
        self.write_config()
        module = self.grader()
        with self.assertRaises(module.GraderError):
            module.grade(self.job)

    def test_missing_test_main_is_configuration_error(self):
        self.config["mainClass"] = "MissingChecks"
        self.write_config()
        module = self.grader()
        with self.assertRaises(module.GraderError):
            module.grade(self.job)

    def test_harness_exit_two_is_not_student_failure(self):
        (self.job / "tests/Checks.java").write_text(
            "public class Checks { public static void main(String[] a) { System.exit(2); } }"
        )
        module = self.grader()
        with self.assertRaises(module.GraderError):
            module.grade(self.job)

    def test_timeout_is_bounded_student_failure(self):
        self.source("while (true) {}")
        result = self.grader().grade(self.job)
        self.assertEqual(result["score"], 0)
        self.assertTrue(result["timed_out"])

    def test_output_flood_is_bounded(self):
        self.source('while (true) { System.out.println("x".repeat(8192)); }')
        result = self.grader().grade(self.job)
        self.assertEqual(result["score"], 0)
        self.assertLessEqual(len(result.get("output", "").encode()), 65536)
        self.assertLess(len(json.dumps(result).encode()), 1024 * 1024)

    def test_cli_harness_failure_is_diagnostic_and_never_a_score(self):
        (self.job / "tests/Checks.java").unlink()
        run = subprocess.run(
            [os.sys.executable, str(GRADER), "--job-dir", str(self.job)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 2)
        self.assertIn("Grader failure", run.stderr)
        result = json.loads((self.job / "results/results.json").read_text())
        self.assertFalse(result["gradable"])
        self.assertTrue(result["grading_error"])
        self.assertNotIn("score", result)

    def test_cli_writes_results_for_prairielearn(self):
        self.grader()
        run = subprocess.run(
            [os.sys.executable, str(GRADER), "--job-dir", str(self.job)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        result = json.loads((self.job / "results/results.json").read_text())
        self.assertEqual(result["score"], 1)


if __name__ == "__main__":
    unittest.main()
