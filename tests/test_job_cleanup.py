"""Очистка приватного scratch без настоящего запуска контейнеров."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import grading_job as jobs
from test_selected_file_delivery import manifest, row
from gradle_unit_fixtures import registry

IMAGE = 'sha256:' + 'd' * 64


class JobCleanup(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.manifest = manifest()
        self.registry = registry()
        self.registry['profiles']['java25-junit-v1']['image'] = IMAGE

    def prepare(self, public=False):
        if public:
            self.manifest['projects'][0]['verificationTests'] = [row('PublicTest.java', b'public')]
        job = jobs.prepare_job(self.manifest, Path(self.temp), 'demo/exr-answer', 'starter', registry=self.registry)
        self.addCleanup(lambda: shutil.rmtree(job.root) if job.root.exists() and not job.root.is_symlink() else None)
        return job

    def execute(self, job, outcomes=None):
        outcomes = iter(outcomes or [SimpleNamespace(returncode=0, stderr='')])
        def run(command, **kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        with patch.object(jobs, 'validate'), patch.object(jobs, '_junit_result_helpers', return_value={'unique_json_object': dict}), patch.object(jobs.subprocess, 'run', side_effect=run):
            for root in [job.root, job.root/'public-verification']:
                if root.is_dir():
                    (root/'results').mkdir()
                    (root/'results/results.json').write_text(json.dumps({'infrastructure':'complete', 'score':1}))
            return jobs.run_job(job, 'container', self.registry)

    def test_permission_fallback_uses_only_prepared_mount_and_exact_image(self):
        job = self.prepare()
        self.execute(job)
        with patch.object(jobs.secrets, 'token_hex', return_value='f'*24), patch.object(jobs.shutil, 'rmtree', side_effect=[PermissionError('mixed owner'), None]) as remove, patch.object(jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr='')) as run:
            jobs.cleanup_job(job, 'container')
        self.assertEqual(remove.call_count, 2)
        self.assertEqual(run.call_args.args[0], ['docker','run','--rm','--name','plcleanup-'+'f'*24,'--network','none','--read-only','--entrypoint','/bin/chown','--mount',f'type=bind,src={job.root},dst=/grade,bind-recursive=disabled',IMAGE,'-Rh',f'{os.getuid()}:{os.getgid()}','/grade'])
        self.assertEqual(run.call_args.kwargs, {'capture_output':True, 'text':True, 'timeout':10})

    def test_replaced_root_after_ownership_command_blocks_second_deletion(self):
        job = self.prepare(); self.execute(job)
        original = job.root.with_name(job.root.name+'-original')
        def chown(*args, **kwargs):
            job.root.rename(original); job.root.mkdir()
            self.addCleanup(lambda: shutil.rmtree(original))
            return SimpleNamespace(returncode=0, stderr='')
        with patch.object(jobs.shutil, 'rmtree', side_effect=[PermissionError(), None]) as remove, patch.object(jobs.subprocess, 'run', side_effect=chown):
            with self.assertRaises(jobs.JobError): jobs.cleanup_job(job, 'container')
            self.assertEqual(remove.call_count, 1)

    def test_ordinary_cleanup_and_host_or_nonpermission_failures_never_run_docker(self):
        job = self.prepare()
        for backend, error in [('container', None), ('host', PermissionError()), ('container', OSError('io'))]:
            with self.subTest(backend=backend, error=error), patch.object(jobs.shutil, 'rmtree', side_effect=error), patch.object(jobs.subprocess, 'run') as run:
                if error:
                    with self.assertRaises(OSError): jobs.cleanup_job(job, backend)
                else: jobs.cleanup_job(job, backend)
                run.assert_not_called()

    def test_unknown_live_failed_timeout_and_public_child_block_all_deletion(self):
        timeout = subprocess.TimeoutExpired('docker', 1)
        for public, outcomes in [(False, [OSError('unknown')]), (False, [timeout, SimpleNamespace(returncode=1, stderr='denied')]), (False, [timeout, timeout]), (True, [SimpleNamespace(returncode=0, stderr=''), timeout, SimpleNamespace(returncode=1, stderr='denied')])]:
            with self.subTest(public=public, outcomes=outcomes):
                job = self.prepare(public)
                self.execute(job, outcomes)
                with patch.object(jobs, 'validate', side_effect=jobs.JobError('invalid retry')):
                    with self.assertRaises(jobs.JobError): jobs.run_job(job, 'container', self.registry)
                with patch.object(jobs.shutil, 'rmtree') as remove, patch.object(jobs.subprocess, 'run') as run:
                    with self.assertRaises(jobs.JobError): jobs.cleanup_job(job, 'container')
                    remove.assert_not_called()
                    run.assert_not_called()

    def test_retry_after_failed_container_removal_cannot_forget_live_container(self):
        job = self.prepare()
        self.execute(job, [subprocess.TimeoutExpired('docker', 1), SimpleNamespace(returncode=1, stderr='denied')])
        original_name = job.containerName
        with patch.object(jobs, 'validate'), patch.object(jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr='')) as run, patch.object(jobs.secrets, 'token_hex') as name:
            with self.assertRaises(jobs.JobError): jobs.run_job(job, 'container', self.registry)
            run.assert_not_called()
            name.assert_not_called()
        self.assertEqual(job.containerName, original_name)
        self.assertFalse(job._containers_stopped)
        with patch.object(jobs.shutil, 'rmtree') as remove:
            with self.assertRaises(jobs.JobError): jobs.cleanup_job(job, 'container')
            remove.assert_not_called()

    def test_safe_unlaunched_cleanup_needs_no_image_or_mount_csv(self):
        for backend in ['container', 'host']:
            with self.subTest(backend=backend):
                self.registry['profiles']['java25-junit-v1']['image'] = ''
                parent = Path(self.temp)/('comma,'+backend); parent.mkdir()
                with patch.object(tempfile, 'tempdir', str(parent)):
                    job = self.prepare()
                with patch.object(jobs.shutil, 'rmtree') as remove, patch.object(jobs.subprocess, 'run') as run:
                    jobs.cleanup_job(job, backend)
                    remove.assert_called_once_with(job.root)
                    run.assert_not_called()

    def test_host_completion_allows_ordinary_cleanup_without_docker(self):
        job = self.prepare(public=True)
        del job._containers_stopped
        grader = SimpleNamespace(grade=lambda root, **kwargs: {'infrastructure':'complete', 'score':1})
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
        with patch.object(jobs, 'validate'), patch.object(jobs.importlib.util, 'spec_from_file_location', return_value=spec), patch.object(jobs.importlib.util, 'module_from_spec', return_value=grader), patch.object(jobs.subprocess, 'run') as run:
            self.assertEqual(jobs.run_job(job, 'host', self.registry)['infrastructure'], 'complete')
            with patch.object(jobs.shutil, 'rmtree') as remove:
                jobs.cleanup_job(job, 'host')
                remove.assert_called_once_with(job.root)
            run.assert_not_called()

    def test_validation_or_missing_image_before_launch_allows_cleanup(self):
        for failure in ['validation', 'image']:
            with self.subTest(failure=failure):
                job = self.prepare()
                if failure == 'image': job['imageDigest'] = ''
                with patch.object(jobs, 'validate', side_effect=jobs.JobError('invalid') if failure == 'validation' else None), patch.object(jobs.subprocess, 'run') as run:
                    if failure == 'validation':
                        with self.assertRaises(jobs.JobError): jobs.run_job(job, 'container', self.registry)
                    else:
                        self.assertEqual(jobs.run_job(job, 'container', self.registry)['infrastructure'], 'failure')
                    run.assert_not_called()
                with patch.object(jobs.shutil, 'rmtree') as remove:
                    jobs.cleanup_job(job, 'container')
                    remove.assert_called_once_with(job.root)

    def test_successful_timeout_removal_allows_fallback(self):
        job = self.prepare()
        self.execute(job, [subprocess.TimeoutExpired('docker', 1), SimpleNamespace(returncode=0, stderr='')])
        with patch.object(jobs.shutil, 'rmtree', side_effect=[PermissionError(), None]), patch.object(jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr='')) as run:
            jobs.cleanup_job(job, 'container')
            run.assert_called_once()

    def test_public_completion_allows_fallback_only_after_child_finishes(self):
        job = self.prepare(public=True)
        observed = []
        def run(command, **kwargs):
            # Любое удаление во время grading-фазы запрещено.
            with patch.object(jobs.shutil, 'rmtree') as remove:
                with self.assertRaises(jobs.JobError): jobs.cleanup_job(job, 'container')
                remove.assert_not_called()
            root = job.root if not observed else job.root/'public-verification'
            (root/'results').mkdir()
            (root/'results/results.json').write_text('{"infrastructure":"complete","score":1}')
            observed.append(root)
            return SimpleNamespace(returncode=0, stderr='')
        with patch.object(jobs, 'validate'), patch.object(jobs, '_junit_result_helpers', return_value={'unique_json_object':dict}), patch.object(jobs.subprocess, 'run', side_effect=run):
            result = jobs.run_job(job, 'container', self.registry)
        self.assertEqual(result['publicResult']['score'], 1)
        self.assertEqual(observed, [job.root, job.root/'public-verification'])
        with patch.object(jobs.shutil, 'rmtree', side_effect=[PermissionError(), None]), patch.object(jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stderr='')) as cleanup:
            jobs.cleanup_job(job, 'container')
            cleanup.assert_called_once()

    def test_changed_root_symlink_owner_uid_image_or_unprepared_path_is_rejected(self):
        for change in ['root', 'inode', 'symlink', 'owner', 'uid', 'image', 'unprepared']:
            with self.subTest(change=change):
                job = self.prepare(); self.execute(job)
                contexts = []
                if change == 'root':
                    original = job.root
                    job.root = Path(self.temp)
                    self.addCleanup(setattr, job, 'root', original)
                elif change == 'inode':
                    original = job.root.with_name(job.root.name+'-original')
                    job.root.rename(original); job.root.mkdir()
                    self.addCleanup(shutil.rmtree, original)
                elif change == 'symlink':
                    original = job.root
                    link = Path(self.temp)/'link'; link.symlink_to(original); self.addCleanup(link.unlink); job.root = link
                    self.addCleanup(setattr, job, 'root', original)
                elif change == 'owner':
                    real = Path.lstat
                    contexts.append(patch.object(Path, 'lstat', lambda p: SimpleNamespace(st_dev=real(p).st_dev, st_ino=real(p).st_ino, st_uid=os.getuid()+1, st_mode=real(p).st_mode)))
                elif change == 'uid': contexts.append(patch.object(jobs.os, 'getuid', return_value=os.getuid()+1))
                elif change == 'image': job['imageDigest'] = 'sha256:'+'e'*64
                else:
                    replacement = jobs.GradingJob(job); replacement.root=job.root; job=replacement
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for context in contexts: stack.enter_context(context)
                    remove = stack.enter_context(patch.object(jobs.shutil, 'rmtree', side_effect=PermissionError() if change == 'image' else None))
                    run = stack.enter_context(patch.object(jobs.subprocess, 'run'))
                    with self.assertRaises((jobs.JobError, PermissionError)): jobs.cleanup_job(job, 'container')
                    if change != 'image': remove.assert_not_called()
                    run.assert_not_called()

    def test_mount_csv_separator_in_prepared_scratch_is_rejected(self):
        parent = Path(self.temp)/'comma,parent'; parent.mkdir()
        with patch.object(tempfile, 'tempdir', str(parent)):
            job = self.prepare()
        self.execute(job)
        with patch.object(jobs.shutil, 'rmtree', side_effect=PermissionError()), patch.object(jobs.subprocess, 'run') as run:
            with self.assertRaises(jobs.JobError): jobs.cleanup_job(job, 'container')
            run.assert_not_called()

    def test_chown_failure_timeout_or_retry_failure_is_not_ignored(self):
        for outcome in [SimpleNamespace(returncode=1, stderr='unsupported bind-recursive'), subprocess.TimeoutExpired('docker',10), SimpleNamespace(returncode=0, stderr='')]:
            job = self.prepare(); self.execute(job)
            with patch.object(jobs.shutil, 'rmtree', side_effect=PermissionError()), patch.object(jobs.subprocess, 'run', side_effect=outcome if isinstance(outcome, Exception) else None, return_value=outcome):
                with self.assertRaises((jobs.JobError, OSError)): jobs.cleanup_job(job, 'container')

    def test_ownership_timeout_removes_only_its_named_container_without_retrying_rmtree(self):
        cases = [
            (SimpleNamespace(returncode=0, stderr=''), 'timed out; container removed'),
            (SimpleNamespace(returncode=1, stderr='No such container'), 'timed out; container removed'),
            (SimpleNamespace(returncode=1, stderr='denied'), 'container cleanup failed: denied'),
            (subprocess.TimeoutExpired('docker rm',10), 'container cleanup failed'),
            (OSError('daemon unavailable'), 'container cleanup failed'),
        ]
        for removal, message in cases:
            with self.subTest(removal=removal):
                job=self.prepare(); self.execute(job)
                with patch.object(jobs.secrets, 'token_hex', return_value='a'*24), patch.object(jobs.shutil, 'rmtree', side_effect=PermissionError()) as remove, patch.object(jobs.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('docker run',10), removal]) as run:
                    with self.assertRaisesRegex(jobs.JobError, message): jobs.cleanup_job(job, 'container')
                self.assertEqual(remove.call_count, 1)
                self.assertEqual(run.call_count, 2)
                command=run.call_args_list[0].args[0]
                self.assertEqual(command[command.index('--name')+1], 'plcleanup-'+'a'*24)
                self.assertEqual(run.call_args_list[1].args[0], ['docker','rm','--force','plcleanup-'+'a'*24])
                self.assertEqual(run.call_args_list[1].kwargs, {'capture_output':True, 'text':True, 'timeout':10})

    def test_cli_retains_results_on_ownership_command_failure_or_timeout(self):
        spec=importlib.util.spec_from_file_location('cleanup_failure_cli', jobs.ROOT/'tools/check-course.py')
        cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        root=Path(self.temp); source=root/'manifest.json'; source.write_text(json.dumps(self.manifest)); output=root/'report.json'
        for outcome in [SimpleNamespace(returncode=1, stderr='unsupported bind-recursive'), subprocess.TimeoutExpired('docker',10)]:
            with self.subTest(outcome=outcome):
                job=self.prepare(); self.execute(job); result={'score':1,'publicResult':{'score':1}}
                with patch.object(sys,'argv',['check-course.py','--manifest',str(source),'--output',str(output)]), patch.object(cli,'prepare_job',return_value=job), patch.object(cli,'run_job',return_value=result), patch.object(cli,'preserve_build_logs'), patch.object(jobs.shutil,'rmtree',side_effect=PermissionError()), patch.object(jobs.subprocess,'run',side_effect=outcome if isinstance(outcome, Exception) else None, return_value=outcome):
                    self.assertEqual(cli.main(),2)
                report=json.loads(output.read_text())
                self.assertEqual(report['results'],[result])
                self.assertEqual(report['classification'],'infrastructure-failure')

    def test_cli_retains_results_and_logs_before_cleanup_failure(self):
        spec=importlib.util.spec_from_file_location('cleanup_cli', jobs.ROOT/'tools/check-course.py')
        cli=importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        root=Path(self.temp); source=root/'manifest.json'; source.write_text(json.dumps(self.manifest)); output=root/'report.json'
        job=self.prepare(); observed=[]; result={'score':1,'publicResult':{'score':1}}
        def execute(*args): observed.append('run-public-complete'); return result
        with patch.object(sys,'argv',['check-course.py','--manifest',str(source),'--output',str(output)]), patch.object(cli,'prepare_job',return_value=job), patch.object(cli,'run_job',side_effect=execute), patch.object(cli,'preserve_build_logs',side_effect=lambda *args: observed.append('logs')), patch.object(jobs.shutil,'rmtree',side_effect=PermissionError('mixed owner')):
            self.assertEqual(cli.main(),2)
        report=json.loads(output.read_text())
        self.assertEqual(report['results'],[result])
        self.assertEqual(report['classification'],'infrastructure-failure')
        self.assertEqual(observed,['run-public-complete','logs'])
