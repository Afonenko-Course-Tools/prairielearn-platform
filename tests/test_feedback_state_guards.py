"""Различающие guards текущего producer → signed decoder → native feedback.

Только grants/publication/quota используют явно диагностическую временную копию
закрытого модуля. Обычные records/scope/parallel исполняют production sources.
"""
from collections.abc import Mapping, Sequence
import copy
from pathlib import Path
import os
import shutil
from typing import Literal, Protocol, TYPE_CHECKING, runtime_checkable
import unittest
from unittest.mock import patch

import test_grading_job as fixtures
from grading_types import JavaOutcome
from platform_modules import load_student_feedback

if TYPE_CHECKING:
    from junit_result import AssertionCheck, JUnitCounts

ROOT = fixtures.ROOT
FIXTURES = Path(__file__).resolve().parent / 'feedback-state-guards'
MODULE = ROOT / 'runtime/java25-junit-v1/feedback/module'
INTERNAL = Path('org/prairielearn/feedback/internal')
ADAPTER = 'org.prairielearn.feedback.PlatformJUnitAdapter'
Diagnostic = Literal['none', 'grant', 'commit', 'end', 'quota', 'array-quota']
Mutation = Literal['none', 'schema', 'guard', 'trusted-root', 'reader', 'bridge']
RunResult = tuple[int, str, Literal['timeout', 'output_limit'] | None]
feedback = load_student_feedback(ROOT / 'runtime/student_feedback.py')
PARALLEL_PREFIX = '[engine:junit-jupiter]/[class:AnswerTest]'
PARALLEL_SEEDS: dict[str, int] = {
    PARALLEL_PREFIX + '/[method:first()]': 101,
    PARALLEL_PREFIX + '/[method:second()]': 202,
    PARALLEL_PREFIX + '/[test-template:row(int)]/[test-template-invocation:#1]': 301,
    PARALLEL_PREFIX + '/[test-template:row(int)]/[test-template-invocation:#2]': 302,
    PARALLEL_PREFIX + '/[test-factory:generated()]/[dynamic-test:#1]': 401,
    PARALLEL_PREFIX + '/[test-factory:generated()]/[dynamic-test:#2]': 402,
}


@runtime_checkable
class _BoundedRun(Protocol):
    def __call__(self, command: Sequence[str], cwd: Path, timeout: float,
             output_limit: int = 65536, *,
             env: Mapping[str, str] | None = None) -> RunResult: ...


def _once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise AssertionError('Изменился диагностический anchor: ' + old)
    return text.replace(old, new)


class FeedbackStateGuards(unittest.TestCase):
    case: fixtures.JUnitJob
    diagnostic: Diagnostic
    mutation: Mutation
    parallel: bool
    compilations: int
    launches: int
    refusals: list[str]

    def setUp(self) -> None:
        # Композиция сохраняет действующий fixture и не наследует его test_*.
        self.case = fixtures.JUnitJob('test_existing_junit_suite_runs_without_course_main')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.diagnostic = 'none'
        self.mutation = 'none'
        self.parallel = False
        self.compilations = 0
        self.launches = 0
        self.refusals = []
        self.case.cfg['limits']['run-seconds'] = 12

    def install(self, name: str) -> None:
        job = self.case.job
        for folder in ('tests', 'student'):
            for path in (job / folder).glob('*.java'):
                path.unlink()
        for folder, names in (('tests', ('AnswerTest.java', 'GuardTwin.java')),
                              ('student', ('Student.java',))):
            for name_part in names:
                source = FIXTURES / name / name_part
                if source.is_file():
                    shutil.copyfile(source, job / folder / name_part)
        if not (job / 'student/Student.java').is_file():
            (job / 'student/Student.java').write_text('public class Student {}\n')
        self.case.cfg['sourceFiles'] = ['Student.java']
        self.case.cfg['testFiles'] = [p.name for p in sorted((job / 'tests').glob('*.java'))]

    def diagnostic_module(self) -> Path:
        target = self.case.job / 'diagnostic-module'
        shutil.copytree(MODULE, target)
        shutil.copyfile(FIXTURES / 'diagnostics/GuardDiagnostics.java',
                        target / INTERNAL / 'GuardDiagnostics.java')
        source = target / INTERNAL / 'State.java'
        text = source.read_text()
        if self.diagnostic in ('commit', 'end'):
            commit = '      synchronized (LOCK) {\n        if (live(context)) {\n          handle.values = check;'
            text = _once(text, commit,
                         '      if (context.grant != null) GuardDiagnostics.pause("commit");\n' + commit)
            end = '    if (check == null)\n      return;\n    synchronized (LOCK) {\n      if (check.ready && live(check.context))'
            text = _once(text, end,
                         '    if (check == null)\n      return;\n'
                         '    if (check.context.grant != null) GuardDiagnostics.pause("end");\n'
                         '    synchronized (LOCK) {\n      if (check.ready && live(check.context))')
        if self.diagnostic in ('commit', 'end', 'quota', 'array-quota'):
            text = _once(text, '      return List.copyOf(result);',
                         '      var frozen = List.copyOf(result);\n'
                         '      GuardDiagnostics.capture(frozen);\n      return frozen;')
        source.write_text(text)
        source = target / INTERNAL / 'RuntimeIdentity.java'
        source.write_text(_once(source.read_text(),
                                '    boolean expectedInternalOpen = false;',
                                '    boolean expectedInternalOpen = true;'))
        if self.diagnostic == 'grant':
            source = target / INTERNAL / 'Timeouts.java'
            text = source.read_text()
            text = _once(text, '        State.deactivate(grant, activation, true);',
                         '        State.deactivate(grant, activation, true);\n'
                         '        GuardDiagnostics.afterClosed(grant);')
            source.write_text(text)
        return target

    def run_job(self) -> JavaOutcome:
        runner = fixtures.grader
        original: object = getattr(runner, '_run', None)
        if not isinstance(original, _BoundedRun):
            raise RuntimeError('Штатный bounded _run недоступен')

        def invoke(command: Sequence[str], cwd: Path, timeout: float,
                   output_limit: int = 65536, *,
                   env: Mapping[str, str] | None = None) -> RunResult:
            argv = list(command)
            if str(MODULE / INTERNAL / 'State.java') in argv:
                self.compilations += 1
                if self.diagnostic != 'none':
                    copy = self.diagnostic_module()
                    argv = [str(copy / Path(a).relative_to(MODULE))
                            if a.startswith(str(MODULE) + '/') else
                            str(copy) if a == str(MODULE) else a for a in argv]
                    argv.append(str(copy / INTERNAL / 'GuardDiagnostics.java'))
            if ADAPTER in argv:
                self.launches += 1
                module = Path(argv[argv.index('--module-path') + 1].split(os.pathsep)[0])
                policy = module / INTERNAL / 'policy.properties'
                if self.diagnostic in ('quota', 'array-quota'):
                    policy.write_text(policy.read_text() + '\nsnapshotBytes=16\n')
                if self.mutation != 'none':
                    self.mutate(module, policy)
                options: list[str] = []
                if self.diagnostic != 'none':
                    options.extend(['--add-opens',
                                    'org.prairielearn.feedback/org.prairielearn.feedback.internal=ALL-UNNAMED',
                                    '-Dfeedback.guard.diagnostic=' + self.diagnostic])
                if self.parallel:
                    options.extend(['-Djunit.jupiter.execution.parallel.enabled=true',
                                    '-Djunit.jupiter.execution.parallel.config.strategy=fixed',
                                    '-Djunit.jupiter.execution.parallel.config.fixed.parallelism=4',
                                    '-Djunit.jupiter.execution.parallel.config.fixed.max-pool-size=4'])
                argv[argv.index('--module-path'):argv.index('--module-path')] = options
            result = original(argv, cwd, timeout, output_limit, env=env)
            if ADAPTER in argv and result[0] != 0:
                self.refusals.append(result[1])
            return result

        with patch.object(runner, '_run', invoke):
            return self.case.run_job()

    def mutate(self, module: Path, policy: Path) -> None:
        extra = {
            'schema': 'projection.AnswerTest$Value=wrong\\:I\n',
            'guard': 'projectionGuard.AnswerTest$Value=0\n',
            'trusted-root': 'trustedRoot=' + str(self.case.job / 'student') + '\n',
            'reader': 'readerBci=-1\n',
        }
        if self.mutation == 'bridge':
            path = next(module.parent.joinpath('trusted').glob('AnswerTest$Value.class'))
            data = path.read_bytes()
            if data.count(b'$pl$c3$component') != 1:
                raise AssertionError('Не найден единственный current bridge')
            path.write_bytes(data.replace(b'$pl$c3$component', b'$pl$c3$componenx'))
        elif self.mutation != 'none':
            policy.write_text(policy.read_text() + '\n' + extra[self.mutation])

    def successful_counts(self, result: JavaOutcome, leaves: int) -> 'JUnitCounts':
        self.assertEqual(result['classification'], 'success', result)
        self.assertEqual(result.get('score'), 1)
        if 'counts' not in result:
            self.fail('Отсутствует настоящий отчёт JUnit')
        counts = result['counts']
        self.assertEqual((counts['executed'], counts['passed'], counts['failed']), (leaves, leaves, 0))
        self.assertTrue(counts['complete'])
        self.assertEqual(counts['eventErrors'], 0)
        self.assertEqual(len({c['id'] for c in counts['cases']}), leaves)
        native = feedback.student_result(result, self.case.cfg)
        self.assertEqual(native.get('score'), 1)
        self.assertEqual(len(native.get('tests', [])), leaves)
        self.assertEqual((self.compilations, self.launches), (1, 1))
        return counts

    def checks(self, counts: 'JUnitCounts', method: str) -> list['AssertionCheck']:
        matches = [c for c in counts['cases'] if '[method:' + method + '(' in c['id']]
        self.assertEqual(len(matches), 1, method)
        return matches[0].get('checks', [])

    def test_hostile_records_are_bounded_without_user_code(self) -> None:
        self.install('records')
        counts = self.successful_counts(self.run_job(), 5)
        normal = self.checks(counts, 'fields')[0]
        self.assertEqual(normal['actual'], '{id=17, data=["поле"]}')
        self.assertEqual(normal['availability'], 'complete')
        for method, marker in [('customList', '<opaque:Student$HostileList>'),
                               ('cycle', '<cycle>'), ('foreign', '<opaque:GuardTwin>'),
                               ('collision', '<opaque:AnswerTest$Collision>')]:
            check = self.checks(counts, method)[0]
            self.assertIn(marker, check['actual'])
            self.assertTrue(check['availability'].startswith('incomplete'), check)

    def test_parent_scope_depth_and_revoked_ancestor(self) -> None:
        self.install('scope')
        counts = self.successful_counts(self.run_job(), 4)
        for method, required, forbidden in [('restore', {'77', '78', '79'}, set[str]()),
                                             ('directWorker', {'801', '802'}, {'899'}),
                                             ('ancestor', {'811', '814'}, {'812', '813'}),
                                             ('depth', set[str](), {'600'})]:
            values = {c['actual'] for c in self.checks(counts, method)}
            self.assertTrue(required <= values, (method, values))
            self.assertFalse(forbidden & values, (method, values))
        self.assertTrue(any(c['availability'] == 'incomplete: timeout depth'
                            for c in self.checks(counts, 'depth')))

    def test_real_parallel_workers_keep_unique_leaf_values(self) -> None:
        self.install('parallel')
        self.parallel = True
        counts = self.successful_counts(self.run_job(), 6)
        self.assert_parallel_values(counts)
        # Смена владельца всей тройки не должна пройти даже при тех же UID,
        # display names, числе checks и общем множестве наблюдаемых значений.
        uids = list(PARALLEL_SEEDS)
        for offset in (0, 2, 4):
            left_id, right_id = uids[offset:offset + 2]
            corrupted = copy.deepcopy(counts)
            leaves = {leaf['id']: leaf for leaf in corrupted['cases']}
            left, right = leaves[left_id], leaves[right_id]
            left['checks'], right['checks'] = right.get('checks', []), left.get('checks', [])
            with self.subTest(swapped=(left_id, right_id)), self.assertRaises(AssertionError):
                self.assert_parallel_values(corrupted)

    def assert_parallel_values(self, counts: 'JUnitCounts') -> None:
        self.assertEqual({leaf['id'] for leaf in counts['cases']}, set(PARALLEL_SEEDS))
        for leaf in counts['cases']:
            seed = PARALLEL_SEEDS[leaf['id']]
            values = tuple(sorted(int(check['actual']) for check in leaf.get('checks', [])
                                  if check['actual'].isdigit()))
            self.assertEqual(values, (seed, seed + 1000, seed + 2000), leaf['id'])

    def test_diagnostic_one_use_direct_foreign_and_revoked_grants(self) -> None:
        self.install('grants')
        self.diagnostic = 'grant'
        counts = self.successful_counts(self.run_job(), 1)
        values = {c['actual'] for c in self.checks(counts, 'grants')}
        self.assertTrue({'989', '993', '995', '6'} <= values, values)
        self.assertNotIn('990', values)

    def pending(self, stage: Literal['commit', 'end']) -> None:
        self.install('publication')
        self.diagnostic = stage
        result = self.run_job()
        counts = self.successful_counts(result, 2)
        pending = self.checks(counts, 'freeze')[1]
        self.assertEqual(pending['delegated'], 'unknown')
        self.assertEqual(pending['availability'], 'incomplete: pending observation')
        value = '<unavailable>' if stage == 'commit' else '901'
        self.assertEqual((pending['expected'], pending['actual']), (value, value))
        self.assertEqual([c['actual'] for c in self.checks(counts, 'release')], ['902'])
        native = feedback.student_result(result, self.case.cfg)
        self.assertEqual(native['feedback'].get('feedbackCompleteness'), 'incomplete')

    def test_diagnostic_finish_freezes_pending_commit(self) -> None:
        self.pending('commit')

    def test_diagnostic_finish_freezes_pending_end(self) -> None:
        self.pending('end')

    def test_diagnostic_record_quota_precedes_allocation(self) -> None:
        self.install('quota')
        self.diagnostic = 'quota'
        counts = self.successful_counts(self.run_job(), 1)
        check = self.checks(counts, 'quota')[0]
        self.assertEqual(check['actual'], '<record quota before allocation>')
        self.assertTrue(check['availability'].startswith('incomplete'))

    def test_diagnostic_array_quota_precedes_allocation_and_preserves_delegate(self) -> None:
        self.install('array-quota')
        self.diagnostic = 'array-quota'
        counts = self.successful_counts(self.run_job(), 1)
        check = self.checks(counts, 'quota')[0]
        self.assertEqual(check['actual'], '<quota before array allocation>')
        self.assertEqual(check['expected'], '<quota before array allocation>')
        self.assertEqual(check['delegated'], 'threw')
        self.assertTrue(check['availability'].startswith('incomplete'))

    def test_stale_projection_schema_guard_and_origin_refuse_before_junit(self) -> None:
        self.install('quota')
        mutations: tuple[tuple[Mutation, str], ...] = (
            ('schema', 'Stale projection schema'), ('guard', 'Invalid projection admission'),
            ('trusted-root', 'Stale trusted class'))
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation):
                self.mutation = mutation
                with self.assertRaisesRegex(fixtures.grader.GraderError,
                                            'JUnit execution did not produce complete reports'):
                    self.run_job()
                self.assertIn(expected, self.refusals[-1])
        self.assertEqual(self.launches, 3)

    def test_stale_reader_callsite_never_exposes_record_fields(self) -> None:
        self.install('quota')
        self.mutation = 'reader'
        counts = self.successful_counts(self.run_job(), 1)
        check = self.checks(counts, 'quota')[0]
        self.assertEqual(check['availability'], 'incomplete: observation failed')
        self.assertEqual((check['actual'], check['expected']), ('<unavailable>', '<unavailable>'))

    def test_stale_bridge_is_tool_failure_without_student_zero(self) -> None:
        self.install('quota')
        self.mutation = 'bridge'
        with self.assertRaisesRegex(fixtures.grader.GraderError,
                                    'Trusted check raised an unexpected exception outside student code'):
            self.run_job()


if __name__ == '__main__':
    unittest.main()
