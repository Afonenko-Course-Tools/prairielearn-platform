import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).parents[1]
class FishGraderTests(unittest.TestCase):
    def test_all_cases_share_outer_deadline_as_student_timeout(self):
        path=ROOT/'images/fish-git-grader/grade.py'
        spec=importlib.util.spec_from_file_location('fishdeadline',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);(job/'student').mkdir();(job/'tests').mkdir()
            cfg={'schemaVersion':1,'runtime':'fish-git-v1','mode':'implementation','sourceFiles':['answer.fish'],'testFiles':['checks.py'],'limits':{'outer-seconds':1,'run-seconds':1,'compile-seconds':5,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
            (job/'tests/grading-job.json').write_text(json.dumps(cfg))
            (job/'tests/checks.py').write_text("def cases(tests):\n return [{},{},{}]\ndef check(root, inputs):\n return [('finished',True)]\n")
            (job/'student/answer.fish').write_text('sleep 0.6\n')
            result=m.grade(job)
            self.assertEqual(result['classification'],'student-timeout')
            self.assertEqual(result['infrastructure'],'complete')

    def test_reference_and_wrong_answer_use_trusted_result_checks(self):
        path=ROOT/'images/fish-git-grader/grade.py'
        self.assertTrue(path.is_file(),'fish runtime is absent')
        spec=importlib.util.spec_from_file_location('fishgrader',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);(job/'student').mkdir();(job/'tests').mkdir()
            cfg={'schemaVersion':1,'runtime':'fish-git-v1','mode':'implementation','sourceFiles':['solution.fish'],'testFiles':['checks.py','input.txt'],'limits':{'outer-seconds':30,'run-seconds':1,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
            cfg['limits']['compile-seconds']=5
            (job/'tests/grading-job.json').write_text(json.dumps(cfg))
            (job/'tests/input.txt').write_text('first\n')
            (job/'tests/checks.py').write_text("def cases(tests):\n return [{'input.txt':'first\\n'},{'input.txt':'other\\n'}]\ndef check(root, inputs):\n from pathlib import Path\n p=Path(root)/'out.txt'\n return [('twice',p.is_file() and not p.is_symlink() and p.read_text()==inputs['input.txt']*2)]\n")
            source=job/'student/solution.fish'
            source.write_text("cat < input.txt > out.txt\ncat < input.txt >> out.txt\n")
            result=m.grade(job);self.assertEqual(result['score'],1);self.assertEqual(result['counts']['executed'],2)
            source.write_text("echo first > out.txt\necho first >> out.txt\n")
            result=m.grade(job);self.assertLess(result['score'],1)
            source.write_text('"broken\n');self.assertEqual(m.grade(job)['studentCompilation'],'failure')
