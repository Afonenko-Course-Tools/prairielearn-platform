"""Общий watchdog JUnit остаётся infra, но объясняет предел времени без private данных."""
import json
import math
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from gradle_unit_fixtures import registry as unit_registry
import test_plain_runtime as fixtures

ROOT = Path(__file__).resolve().parents[1]
student_result = runpy.run_path(str(ROOT / 'runtime/student_feedback.py'))['student_result']
grader = fixtures.grader
CANARY = 'PRIVATE_WATCHDOG_PATH_STACK_CANARY'


class WatchdogProducer(unittest.TestCase):
    setUp = fixtures.PlainRuntimeTests.setUp

    def stopped_execution(self, reason):
        (self.job / 'tests/grading-job.json').write_text(json.dumps(self.config))
        original = grader._run

        def controlled(command, *args, **kwargs):
            if 'org.prairielearn.feedback.PlatformJUnitAdapter' in command:
                return -9, CANARY, reason
            return original(command, *args, **kwargs)

        # Компиляция и подготовка настоящие; заменён только результат watchdog,
        # чтобы не ждать настоящий бесконечный процесс в каждой регрессии.
        with patch.object(grader, '_run', side_effect=controlled):
            return grader.grade(self.job, registry=unit_registry())

    def test_whole_junit_timeout_returns_existing_infrastructure_fields(self):
        result = self.stopped_execution('timeout')
        self.assertEqual(result['classification'], 'infrastructure-failure')
        self.assertFalse(result['gradable'])
        self.assertTrue(result['grading_error'])
        self.assertIs(result['timed_out'], True)
        self.assertNotIn('score', result)
        self.assertNotIn('counts', result)
        self.assertNotIn('dependentExecution', result)
        import jsonschema
        envelope = {'schemaVersion': 1, 'scope': 'declared', 'backend': 'host',
                    'qualifiedId': 'demo/timeout', 'scenario': 'starter',
                    'runtime': 'java25-junit-v1', 'imageDigest': None, **result}
        jsonschema.validate(envelope, json.loads((ROOT / 'schemas/check-result.schema.json').read_text()))
        # Native Gradle build завершён до JUnit: существующий guard оператора
        # обязан принять эти факты и после watchdog, не подменяя их not-run.
        import test_review_receipts as operator
        proof = {'schemaVersion': 1, 'kind': 'gradle-jar-v1', 'status': 'success',
                 'artifact': {'path': 'build/libs/answer.jar', 'bytes': 1}}
        operator.g._validate_build_observation({**result, 'buildEvidence': proof}, 'answer.jar')

    def test_output_limit_and_incomplete_reports_still_raise_infrastructure(self):
        for reason in ['output-limit', None]:
            with self.subTest(reason=reason), self.assertRaises(grader.GraderError):
                self.stopped_execution(reason)


class WatchdogProjection(unittest.TestCase):
    def result(self):
        return {'classification': 'infrastructure-failure', 'infrastructure': 'failure',
                'gradable': False, 'grading_error': True, 'timed_out': True,
                'message': CANARY, 'output': CANARY, 'diagnostics': {'execution': CANARY}}

    def test_native_message_explains_declared_limit_without_private_details(self):
        native = student_result(self.result(), {'limits': {'run-seconds': 30}})
        self.assertEqual(native['classification'], 'infrastructure-failure')
        self.assertEqual(native['feedback']['kind'], 'infrastructure')
        self.assertFalse(native['gradable'])
        self.assertTrue(native['grading_error'])
        self.assertNotIn('score', native)
        self.assertIn('30 с', native['feedback']['observed'])
        self.assertIn('лимит', native['message'])
        self.assertNotIn(CANARY, json.dumps(native))

    def test_invalid_or_missing_limit_is_not_echoed_or_replaced_by_fake_default(self):
        for value in [None, True, False, 0, -1, math.inf, math.nan, CANARY, {}, [], 10**400]:
            with self.subTest(value=repr(value)):
                native = student_result(self.result(), {'limits': {'run-seconds': value}})
                self.assertIn('лимит', native['message'])
                self.assertNotIn('10 с', native['message'])
                self.assertNotIn(CANARY, json.dumps(native))
        self.assertIn('лимит', student_result(self.result(), {})['message'])

    def test_valid_fractional_limit_and_hostile_descriptor_shape(self):
        self.assertIn('2.5 с', student_result(self.result(), {'limits': {'run-seconds': 2.5}})['message'])
        for descriptor in [None, [], {'limits': None}, {'limits': CANARY}]:
            with self.subTest(descriptor=descriptor):
                native = student_result(self.result(), descriptor)
                self.assertIn('лимит', native['message'])
                self.assertNotIn(CANARY, json.dumps(native))

    def test_ordinary_infrastructure_and_child_timeout_keep_their_feedback(self):
        ordinary = self.result()
        ordinary.pop('timed_out')
        self.assertIn('Проверка недоступна', student_result(ordinary, {})['message'])
        for false_marker in [False, 1, 'true']:
            ordinary['timed_out'] = false_marker
            self.assertIn('Проверка недоступна', student_result(ordinary, {})['message'])
        child = student_result({'classification': 'student-timeout', 'gradable': True,
                                'score': 0, 'timed_out': True}, {'limits': {'run-seconds': 30}})
        self.assertEqual(child['feedback']['kind'], 'timeout')
        self.assertEqual(child['score'], 0)
        self.assertNotIn('30 с', child['message'])

    def test_native_exit_zero_operator_exit_two_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / 'tests').mkdir()
            (job / 'tests/grading-job.json').write_text(json.dumps({'limits': {'run-seconds': 30}}))
            for verification, want_status in [(False, 0), (True, 2)]:
                argv = ['grade.py', '--job-dir', str(job)] + (['--verification'] if verification else [])
                with patch('sys.argv', argv), patch.object(grader, 'grade', return_value=self.result()):
                    status = grader.main()
                self.assertEqual(status, want_status)
                result = json.loads((job / 'results/results.json').read_text())
                self.assertNotIn('score', result)
                if verification:
                    self.assertEqual(result['message'], CANARY)
                else:
                    self.assertIn('30 с', result['message'])
                    self.assertNotIn(CANARY, json.dumps(result))


if __name__ == '__main__':
    unittest.main()
