"""Полное авторское решение не расширяет student source policy."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from gradle_unit_fixtures import registry

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("complete_reference_jobs", ROOT / "tools/grading_job.py")
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)

class ReferenceCompleteSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snapshot = Path(self.tmp.name)
        self.project = self.snapshot / "tasks/p"
        files = {
            "student/Copy.java": "class Copy {}",
            "student/Study.java": "public class Study {public static int answer(){return 0;}}",
            "reference/Study.java": "public class Study {public static int answer(){return Renamed.answer();}}",
            "reference/Renamed.java": "class Renamed {static int answer(){return support.Helper.answer();}}",
            "reference/support/Helper.java": "package support; public class Helper {public static int answer(){return 42;}}",
            "tests/AnswerTest.java": "import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest {@Test void works(){assertEquals(42,Study.answer());}}",
        }
        for name, text in files.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        def selected(name, target):
            return {"projectRelativePath": name, "submissionRelativePath": target,
                    "sha256": hashlib.sha256((self.project / name).read_bytes()).hexdigest()}
        self.fact = {
            "qualifiedId": "demo/exr-reference", "projectRoot": "p",
            "check": {"runtime": "java25-junit-v1", "sourceProfile": {"mode": "implementation", "root": "student", "include": ["**/*.java"]},
                      "references": [{"name": "complete", "root": "reference", "optional": False}]},
            "sources": [selected("student/Copy.java", "Copy.java"), selected("student/Study.java", "Study.java")],
            "trustedTests": [selected("tests/AnswerTest.java", "AnswerTest.java")],
            "references": [{"name": "complete", "sources": [selected("reference/Study.java", "Study.java"), selected("reference/Renamed.java", "Renamed.java"), selected("reference/support/Helper.java", "support/Helper.java")]}],
        }
        self.manifest = {"schemaVersion": 1, "bookRoot": "tasks", "sourceSnapshotHash": "a" * 64, "inventoryHash": "b" * 64, "projects": [self.fact]}
        self.registry = registry()
    def prepare(self, scenario):
        job = jobs.prepare_job(self.manifest, self.snapshot, self.fact["qualifiedId"], scenario, registry=self.registry)
        self.addCleanup(shutil.rmtree, job.root)
        return job
    def test_private_reference_replaces_names_student_policy_unchanged(self):
        reference = self.prepare("reference:complete")
        starter = self.prepare("starter")
        self.assertEqual(reference["grading"]["sourceFiles"], ["Renamed.java", "Study.java", "support/Helper.java"])
        self.assertEqual(starter["grading"]["sourceFiles"], ["Copy.java", "Study.java"])
        self.assertNotIn("additionalJavaSources", reference["grading"])
        self.assertNotIn("additionalJavaSources", starter["grading"])
        self.assertFalse((reference.root / "student/Copy.java").exists())
    def test_undeclared_changed_nonjava_reference_refused(self):
        with self.assertRaises(jobs.JobError): self.prepare("reference:foreign")
        (self.project / "reference/Renamed.java").write_text("changed")
        with self.assertRaises(jobs.JobError): self.prepare("reference:complete")
    def test_reference_compiles_with_existing_grader(self):
        reference = self.prepare("reference:complete")
        spec = importlib.util.spec_from_file_location("unchanged_grade", ROOT / "images/java25-grader/grade.py")
        grade = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grade)
        result = grade.grade(reference.root, registry=self.registry)
        self.assertEqual(result["studentCompilation"], "success")
        self.assertEqual(result["score"], 1)
        self.assertEqual(result["counts"]["executed"], 1)

if __name__ == "__main__": unittest.main()
