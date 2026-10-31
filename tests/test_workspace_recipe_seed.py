"""Реальный Git seed: настройки recipe, учебный текст commit и произвольные файлы."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from delivery4 import seed_proof
from grading_job import JobError


class RecipeSeed(unittest.TestCase):
    def fixture(self, files, *, second_commit=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        work = root / 'work'
        work.mkdir()
        template = root / 'empty-template'
        template.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')

        def git(*args):
            return subprocess.run(
                ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                 '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', *args],
                cwd=work, env=env, capture_output=True, check=True, timeout=20,
            )

        git('init', '-q', '--initial-branch=main', '--object-format=sha1', '--template=' + str(template))
        git('config', 'core.autocrlf', 'false')
        for name, data in files.items():
            (work / name).write_bytes(data)
        git('add', '.')
        git('commit', '-qm', 'Начальное состояние учебного проекта')
        if second_commit:
            name = next(iter(files))
            (work / name).write_bytes(files[name] + b'next\n')
            git('commit', '-qam', 'Второе состояние')
        entries = {}
        for path in work.rglob('*'):
            if not path.is_file():
                continue
            name = path.relative_to(work).as_posix()
            if name.startswith('.git/') and not (
                name in ('.git/HEAD', '.git/config', '.git/index', '.git/refs/heads/main')
                or name.startswith('.git/objects/')
            ):
                continue
            entries['work/' + name] = path.read_bytes()
        return root, entries

    def proof(self, root, entries):
        native = root / 'native'
        prefix = 'questions/fixture/exr-seed/'
        question = native / prefix
        question.mkdir(parents=True)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
                if '/.git/' not in '/' + name:
                    path = question / 'clientFilesQuestion/starter' / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
        raw = stream.getvalue()
        archive_sha = hashlib.sha256(raw).hexdigest()
        manifest = json.dumps({
            'schema': 'pl-git-workspace-seed-v1', 'sha256': archive_sha,
            'files': [{'name': n, 'sha256': hashlib.sha256(v).hexdigest()} for n, v in sorted(entries.items())],
        }).encode()
        for name, data in [('workspace/.pl-seed/starter.zip', raw),
                           ('workspace/.pl-seed/manifest.json', manifest),
                           ('clientFilesQuestion/starter.zip', raw)]:
            path = question / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        payload = {'seed': {
            'schema': 'pl-git-workspace-seed-v1',
            'archive': 'workspace/.pl-seed/starter.zip', 'archiveSha256': archive_sha,
            'manifest': 'workspace/.pl-seed/manifest.json',
            'manifestSha256': hashlib.sha256(manifest).hexdigest(),
        }}
        with patch('subprocess.run', side_effect=AssertionError('Reader must not spawn Git')):
            return seed_proof(native, prefix, payload)

    def test_recipe_autocrlf_false_and_authored_commit_message(self):
        root, entries = self.fixture({'README.md': 'Учебный проект\n'.encode(), 'notes.txt': b'notes\n'})
        self.proof(root, entries)

    def test_initial_tree_does_not_require_specific_filenames(self):
        root, entries = self.fixture({'catalog.tsv': b'name\tvalue\nA\t1\n'})
        self.proof(root, entries)

    def test_unsafe_config_remains_rejected(self):
        for change in ('true', 'input', 'fsmonitor'):
            with self.subTest(change=change):
                root, entries = self.fixture({'README.md': b'fixture\n', 'notes.txt': b'notes\n'})
                config = entries['work/.git/config']
                entries['work/.git/config'] = (config + b'\tfsmonitor = true\n' if change == 'fsmonitor'
                                               else config.replace(b'autocrlf = false', b'autocrlf = ' + change.encode()))
                with self.assertRaises(JobError):
                    self.proof(root, entries)

    def test_workspace_history_still_requires_one_initial_commit(self):
        root, entries = self.fixture({'README.md': b'fixture\n', 'notes.txt': b'notes\n'}, second_commit=True)
        with self.assertRaises(JobError):
            self.proof(root, entries)


if __name__ == '__main__':
    unittest.main()
