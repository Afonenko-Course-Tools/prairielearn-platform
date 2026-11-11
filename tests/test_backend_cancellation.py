"""Управляемая отмена реального Docker Backend без запуска Docker и JVM."""
from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import grading_job as jobs
from gradle_unit_fixtures import registry
from test_selected_file_delivery import manifest

IMAGE = 'sha256:' + 'd' * 64
Removal = subprocess.CompletedProcess[str] | BaseException


def confirmed_removals() -> list[Removal]:
    return [
        subprocess.CompletedProcess(['docker', 'rm'], 0, stdout='', stderr=''),
        subprocess.CompletedProcess(['docker', 'rm'], 1, stdout='', stderr='No such container'),
    ]


def failed_removals(*, repeated_interrupt: bool) -> list[Removal]:
    outcomes: list[Removal] = [
        subprocess.CompletedProcess(['docker', 'rm'], 1, stdout='', stderr='daemon denied removal'),
        subprocess.TimeoutExpired('docker rm', 10),
        OSError('daemon unavailable'),
    ]
    if repeated_interrupt:
        outcomes.append(KeyboardInterrupt('повторная отмена во время удаления'))
    return outcomes


class BackendCancellation(unittest.TestCase):
    def prepare(self) -> jobs.GradingJob:
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='backend-cancel-test-'))
        runtime_registry = registry()
        runtime_registry['profiles']['java25-junit-v1']['image'] = IMAGE
        job = jobs.prepare_job(manifest(), Path(temporary), 'demo/exr-answer', 'starter', registry=runtime_registry)
        self.addCleanup(lambda: shutil.rmtree(job.root) if job.root.exists() else None)
        return job

    @contextmanager
    def docker_boundary(
        self, job: jobs.GradingJob, primary: BaseException, removal: Removal, *, ownership: bool,
    ) -> Generator[list[str], None, None]:
        """Две конечные внешние операции: прерываемый run и удаление его имени."""
        events: list[str] = []
        selected_name: str | None = None
        calls = 0

        def run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal calls, selected_name
            calls += 1
            self.assertLessEqual(calls, 2, 'Неограниченная повторная Docker-очистка')
            self.assertEqual(command[0], 'docker')
            self.assertTrue(job.root.is_dir(), 'Scratch удалён до подтверждения остановки')
            self.assertEqual(kwargs.get('capture_output'), True)
            self.assertEqual(kwargs.get('text'), True)
            timeout = kwargs.get('timeout')
            self.assertIsInstance(timeout, (int, float))
            if not isinstance(timeout, (int, float)):
                raise AssertionError('Внешняя операция должна иметь конечный timeout')
            self.assertGreater(timeout, 0)
            if calls == 1:
                self.assertEqual(command[1], 'run')
                selected_name = command[command.index('--name') + 1]
                self.assertRegex(selected_name, r'^plcleanup-[0-9a-f]{24}$' if ownership else r'^plcheck-[0-9a-f]{24}$')
                self.assertIn(IMAGE, command)
                mount = command[command.index('--mount') + 1]
                self.assertEqual(mount, f'type=bind,src={job.root},dst=/grade' + (',bind-recursive=disabled' if ownership else ''))
                self.assertEqual(timeout, 10 if ownership else job.checked_payload()['grading']['limits']['outer-seconds'])
                events.append('run')
                raise primary
            self.assertEqual(list(command), ['docker', 'rm', '--force', selected_name])
            self.assertLessEqual(timeout, 10)
            events.append('remove')
            if isinstance(removal, BaseException):
                raise removal
            return removal

        with patch.object(jobs.subprocess, 'run', side_effect=run):
            yield events

    @contextmanager
    def ownership_boundary(self, job: jobs.GradingJob) -> Generator[list[str], None, None]:
        """Первая штатная попытка удаления получает внешний отказ владельца."""
        real_remove = shutil.rmtree
        events: list[str] = []

        def remove(path: str | Path, *args: object, **kwargs: object) -> None:
            self.assertEqual(path, job.root)
            events.append('scratch')
            if len(events) == 1:
                raise PermissionError('mixed owner')
            real_remove(path)

        with patch.object(jobs.shutil, 'rmtree', side_effect=remove):
            yield events

    def assert_cleanup_blocked(self, job: jobs.GradingJob) -> None:
        stopped: object = getattr(job, '_containers_stopped')
        self.assertIs(stopped, False, 'Недоказанную остановку нельзя отмечать успешной')
        self.assertTrue(job.root.is_dir())
        with patch.object(jobs.shutil, 'rmtree') as remove, patch.object(jobs.subprocess, 'run') as run:
            with self.assertRaisesRegex(jobs.JobError, 'stopped containers'):
                jobs.cleanup_job(job, 'container')
            remove.assert_not_called()
            run.assert_not_called()
        self.assertTrue(job.root.is_dir())

    def assert_error_retained(self, raised: BaseException, wanted: BaseException) -> None:
        pending = [raised]
        visited: set[int] = set()
        while pending:
            current = pending.pop()
            if current is wanted:
                return
            if id(current) in visited:
                continue
            visited.add(id(current))
            if current.__cause__ is not None:
                pending.append(current.__cause__)
            if current.__context__ is not None:
                pending.append(current.__context__)
        self.fail('Исходная ошибка потеряна в цепочке исключений')

    def test_outer_tool_failure_keeps_exit_and_bounded_streams(self) -> None:
        job = self.prepare()
        process = subprocess.CompletedProcess(['docker', 'run'], 125,
            stdout='startup observation', stderr='daemon cause' + 'x' * 100000)
        with patch.object(jobs.subprocess, 'run', return_value=process):
            result = jobs.run_job(job, 'container')
        self.assertEqual(result['classification'], 'infrastructure-failure')
        self.assertNotIn('score', result)
        diagnostics = result.get('diagnostics', {})
        self.assertEqual(diagnostics.get('container.exitCode'), '125')
        self.assertEqual(diagnostics.get('container.stdout'), 'startup observation')
        self.assertTrue(diagnostics.get('container.stderr', '').startswith('daemon cause'))
        self.assertLessEqual(len(diagnostics.get('container.stderr', '').encode()) +
                             len(diagnostics.get('container.stdout', '').encode()), 65536)

    def test_run_interrupt_removes_own_container_before_scratch_cleanup(self) -> None:
        for removal in confirmed_removals():
            with self.subTest(removal=removal):
                job = self.prepare()
                interrupt = KeyboardInterrupt('исходная отмена run_job')
                with self.docker_boundary(job, interrupt, removal, ownership=False) as events:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        jobs.run_job(job, 'container')
                    self.assertIs(caught.exception, interrupt)
                    self.assertEqual(events, ['run', 'remove'])
                    stopped: object = getattr(job, '_containers_stopped')
                    self.assertIs(stopped, True)
                    jobs.cleanup_job(job, 'container')
                self.assertFalse(job.root.exists())

    def test_run_interrupt_failed_removal_preserves_interrupt_and_blocks_cleanup(self) -> None:
        for removal in failed_removals(repeated_interrupt=True):
            with self.subTest(removal=removal):
                job = self.prepare()
                interrupt = KeyboardInterrupt('исходная отмена run_job')
                with self.docker_boundary(job, interrupt, removal, ownership=False) as events:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        jobs.run_job(job, 'container')
                self.assertIs(caught.exception, interrupt)
                self.assertEqual(events, ['run', 'remove'])
                if isinstance(removal, BaseException):
                    self.assert_error_retained(caught.exception, removal)
                else:
                    self.assertIn('daemon denied removal', str(caught.exception.__cause__) + str(caught.exception.__context__))
                self.assert_cleanup_blocked(job)

    def test_run_timeout_removal_keeps_infrastructure_failure_contract(self) -> None:
        for removal in confirmed_removals():
            with self.subTest(removal=removal):
                job = self.prepare()
                timeout = subprocess.TimeoutExpired('docker run', 1, output=b'before timeout', stderr=b'daemon waiting')
                with self.docker_boundary(job, timeout, removal, ownership=False) as events:
                    result = jobs.run_job(job, 'container')
                    self.assertEqual(result['classification'], 'infrastructure-failure')
                    self.assertEqual(result['infrastructure'], 'failure')
                    self.assertNotIn('score', result)
                    self.assertIn('Outer Docker timeout', str(result.get('message')))
                    self.assertEqual(result.get('diagnostics'), {'stage':'container','container.termination':'timeout','container.stdout':'before timeout','container.stderr':'daemon waiting'})
                    self.assertEqual(events, ['run', 'remove'])
                    stopped: object = getattr(job, '_containers_stopped')
                    self.assertIs(stopped, True)
                    jobs.cleanup_job(job, 'container')
                self.assertFalse(job.root.exists())

    def test_run_timeout_failed_removal_blocks_scratch(self) -> None:
        for removal in failed_removals(repeated_interrupt=False):
            with self.subTest(removal=removal):
                job = self.prepare()
                timeout = subprocess.TimeoutExpired('docker run', 1)
                with self.docker_boundary(job, timeout, removal, ownership=False) as events:
                    result = jobs.run_job(job, 'container')
                self.assertEqual(events, ['run', 'remove'])
                self.assertEqual(result['classification'], 'infrastructure-failure')
                self.assertNotIn('score', result)
                self.assertIn('Outer Docker timeout', str(result.get('message')))
                self.assertIn('cleanup failed', str(result.get('message')))
                self.assert_cleanup_blocked(job)

    def test_ownership_interrupt_removes_own_container_before_retry_cleanup(self) -> None:
        for removal in confirmed_removals():
            with self.subTest(removal=removal):
                job = self.prepare()
                interrupt = KeyboardInterrupt('исходная отмена ownership cleanup')
                with self.ownership_boundary(job) as scratch, self.docker_boundary(job, interrupt, removal, ownership=True) as events:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        jobs.cleanup_job(job, 'container')
                    self.assertIs(caught.exception, interrupt)
                    self.assertEqual(events, ['run', 'remove'])
                    self.assertEqual(scratch, ['scratch'])
                    self.assertTrue(job.root.is_dir())
                    stopped: object = getattr(job, '_containers_stopped')
                    self.assertIs(stopped, True)
                    jobs.cleanup_job(job, 'container')
                    self.assertEqual(scratch, ['scratch', 'scratch'])
                self.assertFalse(job.root.exists())

    def test_ownership_interrupt_failed_removal_preserves_interrupt_and_blocks_cleanup(self) -> None:
        for removal in failed_removals(repeated_interrupt=True):
            with self.subTest(removal=removal):
                job = self.prepare()
                interrupt = KeyboardInterrupt('исходная отмена ownership cleanup')
                with self.ownership_boundary(job) as scratch, self.docker_boundary(job, interrupt, removal, ownership=True) as events:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        jobs.cleanup_job(job, 'container')
                self.assertIs(caught.exception, interrupt)
                self.assertEqual(events, ['run', 'remove'])
                self.assertEqual(scratch, ['scratch'])
                if isinstance(removal, BaseException):
                    self.assert_error_retained(caught.exception, removal)
                else:
                    self.assertIn('daemon denied removal', str(caught.exception.__cause__) + str(caught.exception.__context__))
                self.assert_cleanup_blocked(job)

    def test_ownership_timeout_removal_keeps_timeout_and_allows_later_cleanup(self) -> None:
        for removal in confirmed_removals():
            with self.subTest(removal=removal):
                job = self.prepare()
                timeout = subprocess.TimeoutExpired('docker run', 10)
                with self.ownership_boundary(job) as scratch, self.docker_boundary(job, timeout, removal, ownership=True) as events:
                    with self.assertRaisesRegex(jobs.JobError, 'timed out; container removed') as caught:
                        jobs.cleanup_job(job, 'container')
                    self.assert_error_retained(caught.exception, timeout)
                    self.assertEqual(events, ['run', 'remove'])
                    self.assertEqual(scratch, ['scratch'])
                    stopped: object = getattr(job, '_containers_stopped')
                    self.assertIs(stopped, True)
                    jobs.cleanup_job(job, 'container')
                self.assertFalse(job.root.exists())

    def test_ownership_timeout_failed_removal_preserves_chain_and_blocks_scratch(self) -> None:
        for removal in failed_removals(repeated_interrupt=False):
            with self.subTest(removal=removal):
                job = self.prepare()
                timeout = subprocess.TimeoutExpired('docker run', 10)
                with self.ownership_boundary(job) as scratch, self.docker_boundary(job, timeout, removal, ownership=True) as events:
                    with self.assertRaisesRegex(jobs.JobError, 'cleanup failed') as caught:
                        jobs.cleanup_job(job, 'container')
                self.assertEqual(events, ['run', 'remove'])
                self.assertEqual(scratch, ['scratch'])
                self.assert_error_retained(caught.exception, timeout)
                if isinstance(removal, BaseException):
                    self.assert_error_retained(caught.exception, removal)
                self.assert_cleanup_blocked(job)


if __name__ == '__main__':
    unittest.main()
