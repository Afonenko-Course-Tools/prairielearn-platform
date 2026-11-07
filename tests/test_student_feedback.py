"""Student boundary rejects private canaries, including failed runner reports."""

from collections.abc import Iterable
from gradle_unit_fixtures import unit_platform
import importlib.util, json, unittest
from pathlib import Path
from typing import Protocol, runtime_checkable
from selected_job_fixture import fixture_list, fixture_record


@runtime_checkable
class _CaseSchema(Protocol):
    def validate(self, value: object) -> None: ...
    def iter_errors(self, value: object) -> Iterable[object]: ...


def _case_schema(value: object) -> _CaseSchema:
    if not isinstance(value, _CaseSchema):
        raise AssertionError("Канонический case schema validator недоступен")
    return value

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "student_feedback", ROOT / "runtime/student_feedback.py"
)
if spec is None or spec.loader is None:
    raise RuntimeError("Загрузчик локального Python-модуля недоступен")
feedback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feedback)


class StudentFeedback(unittest.TestCase):
    def test_infrastructure_has_no_score(self):
        value = feedback.student_result({'classification': 'infrastructure-failure', 'score': 0}, {})
        self.assertFalse(value['gradable'])
        self.assertTrue(value['grading_error'])
        self.assertNotIn('score', value)

    def test_compile_error_preserves_file_line_and_message(self):
        value = feedback.student_result({'classification': 'student-compilation-failure',
            'gradable': True, 'score': 0,
            'diagnostics': {'studentCompilation': '/grade/student/demo/A.java:3: error: incompatible types: int cannot be converted to String'}},
            {'sourceFiles': ['demo/A.java']})
        error = value['feedback']['compileErrors'][0]
        self.assertEqual((error['file'], error['line']), ('demo/A.java', 3))
        self.assertIn('int cannot be converted to String', error['message'])

    def test_api_mismatch_preserves_declared_contract(self):
        value = feedback.student_result({'classification': 'student-api-mismatch', 'gradable': True,
            'score': 0, 'apiDiagnostic': {'expected': 'public static int answer()', 'observed': 'missing method'}}, {})
        self.assertEqual(value['score'], 0)
        self.assertEqual(value['feedback']['api']['actual'], 'missing method')

class ActualFishFeedback(unittest.TestCase):
    def test_fish_score_and_runtime_class_without_description_metadata(self):
        import tempfile

        spec = importlib.util.spec_from_file_location(
            "feedback_fish", unit_platform(self) / "images/fish-git-grader/grade.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        grader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grader)
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "student").mkdir()
            (job / "tests").mkdir()
            cfg = {
                "schemaVersion": 1,
                "runtime": "fish-git-v1",
                "mode": "implementation",
                "sourceFiles": ["answer.fish"],
                "testFiles": ["checks.py"],
                "limits": {
                    "outer-seconds": 30,
                    "run-seconds": 1,
                    "compile-seconds": 5,
                    "networking": False,
                    "max-output-bytes": 65536,
                },
                "scoring": {"mode": "weighted"},
                "discovery": {"min-executed": 1, "allow-skipped": False},
            }
            (job / "tests/grading-job.json").write_text(json.dumps(cfg))
            (job / "tests/checks.py").write_text(
                "def cases(tests):\n return [{'input.txt':'A'},{'input.txt':''},{'input.txt':'CLOSED_FISH_CANARY'}]\ndef check(root,inputs):\n actual=(root/'out.txt').read_text()\n return [('copy',actual==inputs['input.txt'],actual)]\n"
            )
            source = job / "student/answer.fish"
            source.write_text("cat input.txt > out.txt\n")
            value = feedback.student_result(grader.grade(job), cfg)
            self.assertNotIn("CLOSED_", json.dumps(value))
            self.assertEqual(value['score'], 1)
            self.assertNotIn('publicCases', value['feedback'])
            source.write_text("echo CLOSED_FISH_RUNTIME >&2\nexit 3\n")
            value = feedback.student_result(grader.grade(job), cfg)
            self.assertEqual(value["feedback"]["kind"], "runtime")
            self.assertNotIn("CLOSED_", json.dumps(value))


@unittest.skipUnless(
    __import__("os").environ.get("PL_FISH_TEST_IMAGE"),
    "Set PL_FISH_TEST_IMAGE to exact local candidate",
)
class NativeFishContainerFeedback(unittest.TestCase):
    def test_same_fish_image_native_and_private_boundary(self):
        import tempfile, subprocess, os

        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "student").mkdir()
            (job / "tests").mkdir()
            cfg = {
                "schemaVersion": 1,
                "runtime": "fish-git-v1",
                "mode": "implementation",
                "sourceFiles": ["answer.fish"],
                "testFiles": ["checks.py"],
                "limits": {
                    "outer-seconds": 30,
                    "run-seconds": 1,
                    "compile-seconds": 5,
                    "networking": False,
                    "max-output-bytes": 65536,
                },
                "scoring": {"mode": "weighted"},
                "discovery": {"min-executed": 1, "allow-skipped": False},
            }
            (job / "tests/grading-job.json").write_text(json.dumps(cfg))
            (job / "tests/checks.py").write_text(
                "def cases(tests):\n return [{'input.txt':'A'},{'input.txt':''},{'input.txt':'CLOSED_FISH_INPUT'}]\ndef check(root,inputs):\n actual=(root/'out.txt').read_text()\n return [('copy',actual==inputs['input.txt'],actual)]\n"
            )
            (job / "student/answer.fish").write_text(
                "cat input.txt > out.txt\necho CLOSED_FISH_CONTAINER\n"
            )
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                "codex-common-b-fish-feedback-01a1585d",
                "--network",
                "none",
                "--cpus",
                "0.9",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--mount",
                "type=bind,src=" + str(job) + ",dst=/grade",
                os.environ["PL_FISH_TEST_IMAGE"],
            ]
            for args, private in [([], False), (["--verification"], True)]:
                run = subprocess.run(
                    command + args, capture_output=True, text=True, timeout=60
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads((job / "results/results.json").read_text())
                if private:
                    self.assertNotIn("executionEvidence", result)
                    self.assertIn("CLOSED_FISH_CONTAINER", json.dumps(result))
                    self.assertNotIn("executionEvidence", result)
                    self.assertEqual(result["containment"], "official-landlock-sbuser")
                else:
                    self.assertNotIn("CLOSED_", json.dumps(result) + run.stderr)
                    self.assertEqual(result['score'], 1)
                    self.assertNotIn('publicCases', result['feedback'])
