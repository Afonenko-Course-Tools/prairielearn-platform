"""Локальные controls entrypoint; не квалификация native host или авторизации."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ENTRYPOINT = Path(__file__).resolve().parents[2] / 'images/sp-git-workspace/entrypoint.sh'
ENV = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
       'GIT_TERMINAL_PROMPT': '0', 'GIT_AUTHOR_NAME': 'Fixture',
       'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
       'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}

def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', *args], cwd=root, env=ENV, text=True).strip()

def inventory(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sp-workspace-')
        self.root = Path(self.temp.name)
        self.home = self.root/'home'
        self.home.mkdir()
        self.student = self.root/'student'
        self.work = self.student/'work'
        self.work.mkdir(parents=True)
        (self.student/'README.md').write_text('Рабочий каталог: work.\n')
        (self.work/'README.md').write_text('Название: учебный проект.\n')
        (self.work/'notes.txt').write_text('Следующая встреча: понедельник.\n')
        git(self.work, 'init', '--initial-branch=main')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-m', 'A')
        self.a = git(self.work, 'rev-parse', 'HEAD')
        self.package()

    def tearDown(self):
        self.temp.cleanup()

    def package(self):
        seed = self.home/'.pl-seed'
        seed.mkdir(exist_ok=True)
        archive = seed/'starter.zip'
        files = []
        with zipfile.ZipFile(archive, 'w') as z:
            for p in sorted(self.student.rglob('*')):
                if p.is_file():
                    name = str(p.relative_to(self.student))
                    z.write(p, name)
                    files.append({'name':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        (seed/'manifest.json').write_text(json.dumps({'schema':'pl-git-workspace-seed-v1','sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':files}))

    def boot(self):
        return subprocess.run(['bash',str(ENTRYPOINT),'true'],cwd=self.home,env=ENV,text=True,capture_output=True)

    def ready(self):
        result = self.boot()
        self.assertEqual(result.returncode,0,result.stderr)
        return self.home/'work'

    def test_seed_contains_only_A_and_restart_preserves_split_index(self):
        # Без bootstrap нет seed; без guard restart теряет staged/unstaged расклад.
        work = self.ready()
        self.assertEqual(git(work,'rev-parse','HEAD'),self.a)
        self.assertEqual(git(work,'rev-list','--count','HEAD'),'1')
        (work/'README.md').write_text('Название: проект измерений.\n')
        (work/'notes.txt').write_text('Следующая встреча: вторник.\n')
        git(work,'add','README.md','notes.txt')
        git(work,'restore','--staged','notes.txt')
        (work/'.untracked').write_text('скрытый незакоммиченный файл\n')
        (self.home/'explanation.md').write_text('Первое восстановление: индекс — понедельник; файл — вторник.\n')
        before = inventory(self.home)
        self.ready()
        self.assertEqual(inventory(self.home),before)
        self.assertEqual(git(work,'show',':notes.txt'),'Следующая встреча: понедельник.')
        self.assertEqual((work/'notes.txt').read_text(),'Следующая встреча: вторник.\n')
        git(work,'commit','-m','Исправить название')
        b = git(work,'rev-parse','HEAD')
        before = inventory(self.home)
        self.ready()
        self.assertEqual(inventory(self.home),before)
        self.assertEqual(git(work,'diff','HEAD^','HEAD','--name-only'),'README.md')
        git(work,'restore','notes.txt')
        (work/'.untracked').unlink()
        self.assertEqual(git(work,'status','--porcelain'),'')
        self.assertEqual(git(work,'rev-parse','HEAD'),b)
        self.assertEqual(git(work,'rev-parse','HEAD^'),self.a)
        before = inventory(self.home)
        self.ready()
        self.assertEqual(inventory(self.home),before)
        identity = json.loads((self.home/'.pl-seed/identity.json').read_text())
        self.assertEqual(identity['seedCommit'],self.a)

    def test_existing_unidentified_work_is_never_overwritten(self):
        work=self.home/'work'
        work.mkdir()
        (work/'notes.txt').write_text('уже существующая работа\n')
        before=inventory(self.home)
        self.assertNotEqual(self.boot().returncode,0)
        self.assertEqual(inventory(self.home),before)

    def test_changed_seed_refuses_restart_without_changing_answer(self):
        work=self.ready()
        (work/'notes.txt').write_text('не терять\n')
        (self.work/'notes.txt').write_text('другая заготовка\n')
        self.package()
        before=inventory(self.home)
        self.assertNotEqual(self.boot().returncode,0)
        self.assertEqual(inventory(self.home),before)

    def test_identity_without_work_never_reseeds(self):
        self.ready()
        shutil.rmtree(self.home/'work')
        before=inventory(self.home)
        self.assertNotEqual(self.boot().returncode,0)
        self.assertEqual(inventory(self.home),before)
        self.assertFalse((self.home/'work').exists())

    def test_invalid_archive_cannot_write_outside_home(self):
        archive=self.home/'.pl-seed/starter.zip'
        with zipfile.ZipFile(archive,'a') as z:
            z.writestr('../escape','не извлекать')
        manifest=json.loads((archive.parent/'manifest.json').read_text())
        manifest['sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
        (archive.parent/'manifest.json').write_text(json.dumps(manifest))
        self.assertNotEqual(self.boot().returncode,0)
        self.assertFalse((self.root/'escape').exists())
        self.assertFalse((self.home/'work').exists())

    def test_unreachable_solution_commit_is_not_a_seed(self):
        (self.work/'README.md').write_text('Название: проект измерений.\n')
        git(self.work,'add','README.md')
        git(self.work,'commit','-m','B, отсутствующий в refs')
        hidden_b=git(self.work,'rev-parse','HEAD')
        git(self.work,'reset','--hard',self.a)
        shutil.rmtree(self.work/'.git/logs',ignore_errors=True)
        self.assertEqual(git(self.work,'rev-list','--count','--all'),'1')
        self.assertEqual(git(self.work,'show',hidden_b+':README.md'),'Название: проект измерений.')
        self.package()
        self.assertNotEqual(self.boot().returncode,0)
        self.assertFalse((self.home/'work').exists())

    def test_unreachable_answer_blob_is_not_a_seed(self):
        answer=self.root/'answer.txt'
        answer.write_text('Название: проект измерений.\n')
        hidden_blob=git(self.work,'hash-object','-w',str(answer))
        self.assertEqual(git(self.work,'cat-file','-t',hidden_blob),'blob')
        self.assertEqual(git(self.work,'rev-list','--count','--all'),'1')
        self.package()
        self.assertNotEqual(self.boot().returncode,0)
        self.assertFalse((self.home/'work').exists())

    def test_packed_unreachable_answer_blob_is_not_a_seed(self):
        answer=self.root/'answer.txt'
        answer.write_text('Название: проект измерений.\n')
        hidden_blob=git(self.work,'hash-object','-w',str(answer))
        objects=git(self.work,'cat-file','--batch-all-objects','--batch-check=%(objectname)')
        subprocess.check_output(['git','pack-objects','.git/objects/pack/seed'],
                                input=objects+'\n',cwd=self.work,env=ENV,text=True)
        git(self.work,'prune-packed')
        self.assertFalse((self.work/'.git/objects'/hidden_blob[:2]/hidden_blob[2:]).exists())
        self.assertEqual(git(self.work,'cat-file','-t',hidden_blob),'blob')
        self.package()
        self.assertNotEqual(self.boot().returncode,0)
        self.assertFalse((self.home/'work').exists())

    def test_restart_preserves_unreachable_student_objects(self):
        work=self.ready()
        answer=self.root/'answer.txt'
        answer.write_text('Личная промежуточная запись студента.\n')
        object_id=git(work,'hash-object','-w',str(answer))
        before=inventory(self.home)
        self.ready()
        self.assertEqual(inventory(self.home),before)
        self.assertEqual(git(work,'cat-file','blob',object_id),'Личная промежуточная запись студента.')

    def test_solution_history_is_not_a_seed(self):
        (self.work/'README.md').write_text('Название: проект измерений.\n')
        git(self.work,'add','README.md')
        git(self.work,'commit','-m','B уже готов')
        self.package()
        self.assertNotEqual(self.boot().returncode,0)
        self.assertFalse((self.home/'work').exists())

if __name__ == '__main__':
    unittest.main()
