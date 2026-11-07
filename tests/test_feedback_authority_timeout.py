"""F1/F2: настоящий named producer, полномочия и неизменная JUnit семантика.

Raw XML/feedback истёкшего trusted leaf живут только в private TemporaryDirectory;
report_key используется штатным decoder в памяти и не публикуется.
"""
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import shutil
from typing import Literal, Protocol, runtime_checkable
import unittest
from unittest.mock import patch

import test_grading_job as fixtures
from grading_types import JavaOutcome
from json_boundary import JSONValue, json_object
from junit_result import AssertionCheck, JUnitCase, JUnitCounts, RawResult, read_junit_xml
from platform_modules import load_student_feedback

ROOT = fixtures.ROOT
FIXTURES = Path(__file__).resolve().parent / 'feedback-state-guards'
ADAPTER = 'org.prairielearn.feedback.PlatformJUnitAdapter'
PREFIX = '[engine:junit-jupiter]/[class:AnswerTest]/[method:'
RunResult = tuple[int, str, Literal['timeout', 'output_limit'] | None]
feedback = load_student_feedback(ROOT / 'runtime/student_feedback.py')


@runtime_checkable
class _BoundedRun(Protocol):
    def __call__(self, command: Sequence[str], cwd: Path, timeout: float,
                 output_limit: int = 65536, *,
                 env: Mapping[str, str] | None = None) -> RunResult: ...


class FeedbackAuthorityTimeout(unittest.TestCase):
    case: fixtures.JUnitJob
    child_calls: int
    adapter_calls: int
    producer_counts: JUnitCounts | None
    producer_raw: RawResult | None
    producer_feedback: dict[str, JSONValue] | None
    producer_xml: dict[str, bytes]

    def setUp(self) -> None:
        self.case = fixtures.JUnitJob('test_existing_junit_suite_runs_without_course_main')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.cfg['limits']['run-seconds'] = 12
        self.child_calls = 0
        self.adapter_calls = 0
        self.producer_counts = None
        self.producer_raw = None
        self.producer_feedback = None
        self.producer_xml = {}

    def install(self, kind: Literal['authority', 'delegates', 'expiry']) -> None:
        group = 'authority-transfer' if kind == 'authority' else 'timeout-contract'
        names = (('AnswerTest.java', 'ForeignHelper.java') if kind == 'authority'
                 else ('ExpiryTest.java',) if kind == 'expiry' else ('AnswerTest.java',))
        for path in (self.case.job / 'tests').glob('*.java'):
            path.unlink()
        shutil.copyfile(FIXTURES / group / 'Student.java', self.case.job / 'student/Student.java')
        for name in names:
            shutil.copyfile(FIXTURES / group / name, self.case.job / 'tests' / name)
        self.case.cfg['sourceFiles'] = ['Student.java']
        self.case.cfg['testFiles'] = list(names)

    def run_job(self, *, capture_expiry: bool = False) -> JavaOutcome:
        original: object = getattr(fixtures.grader, '_run', None)
        if not isinstance(original, _BoundedRun):
            raise RuntimeError('Штатный bounded _run недоступен')

        def invoke(command: Sequence[str], cwd: Path, timeout: float,
                   output_limit: int = 65536, *,
                   env: Mapping[str, str] | None = None) -> RunResult:
            self.child_calls += 1
            capture: tuple[Path, str] | None = None
            if ADAPTER in command:
                self.adapter_calls += 1
                if capture_expiry:
                    # Читается настоящий private input этого job до его штатного удаления Java.
                    parameters = json_object(json.loads(Path(command[-1]).read_text()))
                    destination, key = parameters.get('feedback_file'), parameters.get('report_key')
                    if not isinstance(destination, str) or not isinstance(key, str):
                        raise AssertionError('Отсутствует настоящий private producer binding')
                    capture = Path(destination), key
            result = original(command, cwd, timeout, output_limit, env=env)
            if capture is not None:
                self.assertEqual(result[0], 0, 'Producer не доставил полный отчёт')
                destination, key = capture
                self.producer_feedback = json_object(json.loads(destination.read_bytes()))
                self.producer_xml = {path.name: path.read_bytes()
                                     for path in destination.parent.glob('TEST-*.xml')}
                # Никакого replacement результата: настоящий decoder проверяет те же bytes/HMAC.
                self.producer_raw, self.producer_counts = read_junit_xml(
                    destination.parent, destination, report_key=key)
            return result

        with patch.object(fixtures.grader, '_run', invoke):
            return self.case.run_job()

    def successful(self, result: JavaOutcome, methods: set[str]) -> dict[str, JUnitCase]:
        self.assertEqual(result['classification'], 'success', result)
        self.assertEqual(result['infrastructure'], 'complete')
        self.assertEqual(result.get('score'), 1)
        counts = result.get('counts')
        if counts is None:
            self.fail('Отсутствует настоящий canonical JUnit report')
        expected = {PREFIX + name + '()]' for name in methods}
        self.assertEqual(set(counts['registered']), expected)
        self.assertEqual(set(counts['started']), expected)
        self.assertEqual(counts['outcomes'], {uid: 'successful' for uid in expected})
        self.assertEqual((counts['discovered'], counts['executed'], counts['passed'], counts['failed']),
                         (len(methods), len(methods), len(methods), 0))
        self.assertEqual((counts['skipped'], counts['aborted'], counts['containerFailures'], counts['eventErrors']),
                         (0, 0, 0, 0))
        self.assertTrue(counts['complete'])
        self.assertEqual(counts['failureKinds'], {})
        cases = {case['id']: case for case in counts['cases']}
        self.assertEqual(set(cases), expected)
        native = feedback.student_result(result, self.case.cfg)
        self.assertEqual(native.get('score'), 1)
        self.assertEqual(len(native.get('tests', [])), len(methods))
        self.assertEqual((self.child_calls, self.adapter_calls), (10, 1))
        return cases

    def checks(self, cases: Mapping[str, JUnitCase], method: str) -> list[AssertionCheck]:
        return cases[PREFIX + method + '()]'].get('checks', [])

    def test_foreign_lifecycle_and_scope_never_gain_leaf_authority(self) -> None:
        self.install('authority')
        result = self.run_job()
        cases = self.successful(result, {'authority', 'worker'})
        normal = self.checks(cases, 'authority')
        worker = self.checks(cases, 'worker')
        self.assertEqual([check['actual'] for check in normal], ['4101', '{id=4100}', '4102'])
        self.assertEqual([check['actual'] for check in worker], ['не бросил', '4201', '4202'])
        for leaf in cases.values():
            for check in leaf.get('checks', []):
                self.assertEqual(check['availability'], 'complete')
                self.assertFalse({'999001', '999002', '999003', '999004'}
                                 & {check['expected'], check['actual']})
        self.assertIn('AUTHORITY audits=4 attempts=172 denied=156 foreign=4 fake=0 structural=9',
                      result.get('output', ''))

    def test_preemptive_overloads_and_annotation_scopes_preserve_delegates(self) -> None:
        self.install('delegates')
        cases = self.successful(self.run_job(), {'sevenOverloads', 'invalidArguments', 'customFactory',
                                                'callbackDelegates', 'annotationSame', 'annotationSeparate'})
        seven = self.checks(cases, 'sevenOverloads')
        numeric = [check['actual'] for check in seven if check['actual'].isdigit()]
        self.assertEqual(numeric, [*(str(value) for value in range(7101, 7108)), '7', '0', '0', '7199'])
        timeout_checks = [check for check in seven if check['property'] == 'preemptive timeout']
        self.assertEqual(len(timeout_checks), 9)
        self.assertEqual([check['delegated'] for check in timeout_checks], ['returned'] * 7 + ['threw'] * 2)
        self.assertEqual([check['actual'] for check in self.checks(cases, 'customFactory')][-4:],
                         ['1', '1', '1', '7301'])
        self.assertEqual([check['actual'] for check in self.checks(cases, 'callbackDelegates')][-3:],
                         ['9', '1', '7401'])
        delegated = [check['delegated'] for check in self.checks(cases, 'callbackDelegates')]
        self.assertIn('threw', delegated)
        self.assertIn('returned', delegated)
        for method, value in [('invalidArguments', '7201'), ('annotationSame', '7501'),
                              ('annotationSeparate', '7601')]:
            self.assertEqual(self.checks(cases, method)[-1]['actual'], value)

    def test_expired_annotation_delivers_raw_failed_uid_then_refuses_trusted_score(self) -> None:
        self.install('expiry')
        with self.assertRaisesRegex(fixtures.grader.GraderError,
                                    'Trusted check raised an unexpected exception outside student code'):
            self.run_job(capture_expiry=True)
        counts, raw, produced = self.producer_counts, self.producer_raw, self.producer_feedback
        if counts is None or raw is None or produced is None:
            self.fail('Отсутствует настоящий подписанный producer report до scoring refusal')
        uid = '[engine:junit-jupiter]/[class:ExpiryTest]/[method:expires()]'
        self.assertEqual(counts['outcomes'], {uid: 'failed'})
        self.assertEqual(counts['failureKinds'], {uid: 'infrastructure'})
        self.assertEqual((counts['discovered'], counts['executed'], counts['passed'], counts['failed']), (1, 1, 0, 1))
        self.assertEqual((counts['skipped'], counts['aborted'], counts['containerFailures'], counts['eventErrors']),
                         (0, 0, 0, 0))
        self.assertTrue(counts['complete'])
        self.assertEqual([case['id'] for case in counts['cases']], [uid])
        self.assertEqual([check['actual'] for check in counts['cases'][0].get('checks', [])], ['5601'])
        self.assertEqual(produced.get('verifiedOutcomes'), {uid: 'failed'})
        self.assertEqual(produced.get('failureKinds'), {uid: 'infrastructure'})
        self.assertTrue(self.producer_xml)
        self.assertTrue(any(b'<failure' in data or b'<error' in data for data in self.producer_xml.values()))
        # raw.score — только XML points; grade выше отказал, JavaOutcome/student score не возвращён.
        self.assertEqual(raw['score'], 0)
        self.assertEqual((self.child_calls, self.adapter_calls), (10, 1))


if __name__ == '__main__':
    unittest.main()
