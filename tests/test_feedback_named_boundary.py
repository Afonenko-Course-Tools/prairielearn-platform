"""Два настоящих задания закрытой named-границы в обоих режимах."""
from collections.abc import Mapping, Sequence
import json
import os
import re
from pathlib import Path
import shutil
from typing import Literal, Protocol, runtime_checkable
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import test_grading_job as fixtures
from grading_types import JavaOutcome
from json_boundary import json_object
from junit_result import JUnitCounts, read_junit_xml
from platform_modules import load_student_feedback

ROOT = fixtures.ROOT
FIXTURES = Path(__file__).resolve().parent / 'feedback-state-guards'
ADAPTER = 'org.prairielearn.feedback.PlatformJUnitAdapter'
RunResult = tuple[int, str, Literal['timeout', 'output_limit'] | None]
feedback = load_student_feedback(ROOT / 'runtime/student_feedback.py')


@runtime_checkable
class _BoundedRun(Protocol):
    def __call__(self, command: Sequence[str], cwd: Path, timeout: float,
                 output_limit: int = 65536, *,
                 env: Mapping[str, str] | None = None) -> RunResult: ...


class FeedbackNamedBoundary(unittest.TestCase):
    def exercise(self, mode: Literal['implementation', 'student-tests']) -> None:
        case = fixtures.JUnitJob('test_existing_junit_suite_runs_without_course_main')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.cfg['mode'] = mode
        case.cfg['limits']['run-seconds'] = 12
        student_tests = mode == 'student-tests'
        group = 'named-boundary-student-tests' if student_tests else 'named-boundary'
        source = 'StudentBoundaryTest.java' if student_tests else 'Student.java'
        test = 'Candidate.java' if student_tests else 'NamedBoundaryTest.java'
        for folder, name in (('student', source), ('tests', test)):
            for path in (case.job / folder).glob('*.java'):
                path.unlink()
            shutil.copyfile(FIXTURES / group / name, case.job / folder / name)
        case.cfg['sourceFiles'] = [source]
        case.cfg['testFiles'] = [test]
        original: object = getattr(fixtures.grader, '_run', None)
        if not isinstance(original, _BoundedRun):
            raise RuntimeError('Штатный bounded _run недоступен')
        child_calls = 0
        launches = 0
        decoded: JUnitCounts | None = None

        def invoke(command: Sequence[str], cwd: Path, timeout: float,
                   output_limit: int = 65536, *,
                   env: Mapping[str, str] | None = None) -> RunResult:
            nonlocal child_calls, launches, decoded
            child_calls += 1
            argv = list(command)
            destination: Path | None = None
            key: str | None = None
            if ADAPTER in argv:
                launches += 1
                params = json_object(json.loads(Path(argv[-1]).read_text()))
                output, secret = params.get('feedback_file'), params.get('report_key')
                if not isinstance(output, str) or not isinstance(secret, str):
                    raise AssertionError('Нет настоящего private HMAC binding')
                destination, key = Path(output), secret
                module = Path(argv[argv.index('--module-path') + 1].split(os.pathsep)[0])
                policy = module / 'org/prairielearn/feedback/internal/policy.properties'
                self.assertEqual(policy.is_file(), not student_tests)
                if not student_tests:
                    at = argv.index('--module-path')
                    argv[at:at] = ['-Djunit.jupiter.execution.parallel.enabled=true',
                                   '-Djunit.jupiter.execution.parallel.config.strategy=fixed',
                                   '-Djunit.jupiter.execution.parallel.config.fixed.parallelism=4',
                                   '-Djunit.jupiter.execution.parallel.config.fixed.max-pool-size=4']
            result = original(argv, cwd, timeout, output_limit, env=env)
            if destination is not None and key is not None:
                if student_tests:
                    self.assertEqual(result[0], 0, result[1])
                    _, decoded = read_junit_xml(destination.parent, destination, report_key=key)
                else:
                    self.assertNotEqual(result[0], 0, result[1])
                    self.assertIsNone(result[2], result[1])
                    self.assertIn('NAMED_BOUNDARY normal_checks_complete leaves=2', result[1])
                    for marker in ('9101', '9201'):
                        self.assertEqual(result[1].count(
                            'NAMED_BOUNDARY api_reporter_complete marker=' + marker), 1, result[1])
                    self.assertIn('NAMED_BOUNDARY late_reporter_entered', result[1])
                    self.assertIn('NAMED_BOUNDARY late_reporter_returned', result[1])
                    self.assertEqual(result[1].count(
                        'SecurityException: Reporting requires an active registered leaf'), 1, result[1])
                    self.assertEqual(result[1].count('SecurityException:'), 2, result[1])
                    self.assertIn('PlatformJUnitAdapter.reportingEntryPublished', result[1])
                    self.assertIn('SecurityException: JUnit listener integrity failed', result[1])
                    for other in ('Invalid JUnit listener phase', 'Untrusted JUnit lifecycle',
                                  'Missing qualified JUnit', 'Unexpected JUnit', 'Invalid leaf scope'):
                        self.assertNotIn(other, result[1])
                    self.assertFalse(destination.exists())
                    self.assertFalse(Path(str(destination) + '.signature').exists())
                    leaves: dict[str, ET.Element] = {}
                    for xml in destination.parent.glob('TEST-*.xml'):
                        for leaf in ET.fromstring(xml.read_bytes()).iter('testcase'):
                            if leaf.get('classname') == 'NamedBoundaryTest':
                                name = leaf.get('name', '')
                                self.assertNotIn(name, leaves)
                                leaves[name] = leaf
                    self.assertEqual(set(leaves), {'first(TestReporter)', 'second(TestReporter)'})
                    uids: set[str] = set()
                    for leaf in leaves.values():
                        match = re.search(r'^unique-id: (.+)$', leaf.findtext('system-out', ''), re.M)
                        if match is None:
                            self.fail('Нет настоящего XML UID завершённого leaf')
                        uids.add(match[1].strip())
                        self.assertIsNone(leaf.find('failure'))
                        self.assertIsNone(leaf.find('error'))
                        self.assertIsNone(leaf.find('skipped'))
                    self.assertEqual(uids, {
                        '[engine:junit-jupiter]/[class:NamedBoundaryTest]/[method:' + method
                        + '(org.junit.jupiter.api.TestReporter)]' for method in ('first', 'second')})
            return result

        with patch.object(fixtures.grader, '_run', invoke):
            if not student_tests:
                with self.assertRaisesRegex(fixtures.grader.GraderError,
                                            'JUnit execution did not produce complete reports'):
                    case.run_job()
                self.assertEqual((child_calls, launches), (10, 1))
                return
            result: JavaOutcome = case.run_job()
        self.assertEqual(result['classification'], 'success', result)
        self.assertEqual(result['infrastructure'], 'complete')
        self.assertEqual(result.get('score'), 1)
        counts = result.get('counts')
        if counts is None or decoded is None:
            self.fail('Нет настоящего подписанного отчёта JUnit')
        self.assertEqual(counts, decoded)
        expected = {'[engine:junit-jupiter]/[class:StudentBoundaryTest]/'
                    '[method:boundaryWithoutPolicy(org.junit.jupiter.api.TestReporter)]'}
        self.assertEqual(set(counts['registered']), expected)
        self.assertEqual(set(counts['started']), expected)
        self.assertEqual(counts['outcomes'], {uid: 'successful' for uid in expected})
        self.assertEqual((counts['discovered'], counts['executed'], counts['passed'], counts['failed']),
                         (len(expected), len(expected), len(expected), 0))
        self.assertTrue(counts['complete'])
        self.assertEqual((counts['eventErrors'], counts['containerFailures'], counts['skipped'], counts['aborted']),
                         (0, 0, 0, 0))
        self.assertEqual(counts['failureKinds'], {})
        for report in counts['cases']:
            self.assertNotIn('checks', report)
            self.assertNotIn('expected', report)
            self.assertNotIn('actual', report)
        native = feedback.student_result(result, case.cfg)
        self.assertEqual(native.get('score'), 1)
        self.assertEqual(len(native.get('tests', [])), len(expected))
        self.assertEqual((child_calls, launches), (7, 1))

    def test_named_implementation_refuses_authorized_reporting_of_finished_leaf(self) -> None:
        self.exercise('implementation')

    def test_named_student_tests_remains_without_policy_and_authority(self) -> None:
        self.exercise('student-tests')


if __name__ == '__main__':
    unittest.main()
