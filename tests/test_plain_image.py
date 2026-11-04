"""Публичная проверка собранного образа с настоящими Gradle/JUnit и ролями."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_plain_runtime as fixtures

@unittest.skipUnless(os.environ.get('PL_TEST_IMAGE'), 'Нужен собранный PL_TEST_IMAGE')
class PlainImageTests(unittest.TestCase):
    setUp = fixtures.PlainRuntimeTests.setUp

    def invoke(self):
        (self.job/'tests/grading-job.json').write_text(json.dumps(self.config))
        # The official root supervisor creates protected artifact directories.
        # Return only this test's disposable mount to its host owner before
        # TemporaryDirectory cleanup, including when an assertion fails.
        self.addCleanup(subprocess.run, ['docker','run','--rm','--network=none',
            '--entrypoint','/bin/chown','--mount',f'type=bind,src={self.job},dst=/grade',
            os.environ['PL_TEST_IMAGE'],'-Rh',f'{os.getuid()}:{os.getgid()}','/grade'],
            capture_output=True,text=True,check=True,timeout=10)
        result=subprocess.run(['docker','run','--rm','--network=none','--cpus=2','--memory=512m','--pids-limit=128',
            '--mount',f'type=bind,src={self.job},dst=/grade',os.environ['PL_TEST_IMAGE'],'--verification'],
            capture_output=True,text=True,timeout=35)
        payload=json.loads((self.job/'results/results.json').read_text())
        return result,payload

    def test_native_gradle_jar_and_junit(self):
        self.config.update(runtime='java25-gradle-junit-v1',
            javaBuild={'kind':'gradle-jar-v1','artifact':'answer.jar'})
        self.config['limits'].update({'compile-seconds':20,'outer-seconds':35})
        result,payload=self.invoke()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(payload['score'],1)
        self.assertEqual(payload['containment'],'official-landlock-sbuser')
        self.assertEqual(payload['buildEvidence']['status'],'success')
        self.assertTrue((self.job/'build/libs/answer.jar').is_file())
        self.assertNotIn('executionEvidence',payload)
        self.assertNotIn('sha256',payload['buildEvidence']['artifact'])

    def test_broken_trusted_suite_has_no_score(self):
        (self.job/'tests/AnswerTest.java').write_text('not java')
        result,payload=self.invoke()
        self.assertEqual(result.returncode,2)
        self.assertEqual(payload['classification'],'infrastructure-failure')
        self.assertNotIn('score',payload)
