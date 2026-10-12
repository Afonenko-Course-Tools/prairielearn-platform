import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

@unittest.skipUnless(os.environ.get('PL_FISH_TEST_IMAGE'),'Set PL_FISH_TEST_IMAGE to an actual built fish image')
class FishContainer(unittest.TestCase):
    def test_verified_fish_image_grades_reference_and_wrong_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'student').mkdir();(root/'tests').mkdir()
            cfg={'schemaVersion':1,'runtime':'fish-git-v1','mode':'implementation','sourceFiles':['answer.fish'],'testFiles':['checks.py'],'limits':{'outer-seconds':30,'run-seconds':2,'compile-seconds':5,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
            (root/'tests/grading-job.json').write_text(json.dumps(cfg))
            (root/'tests/checks.py').write_text("def cases(tests):\n return [{}]\ndef check(root,inputs):\n from pathlib import Path\n return [('answer',Path(root,'out.txt').read_text()=='42\\n')]\n")
            for source,expected in [('echo 42 > out.txt\n',1),('echo 0 > out.txt\n',0)]:
                (root/'student/answer.fish').write_text(source)
                result=subprocess.run(['docker','run','--rm','--network','none','--mount','type=bind,src='+str(root)+',dst=/grade',os.environ['PL_FISH_TEST_IMAGE']],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                actual=json.loads((root/'results/results.json').read_text())
                self.assertEqual(actual['score'],expected)
