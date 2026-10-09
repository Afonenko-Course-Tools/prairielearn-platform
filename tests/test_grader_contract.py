"""Entrypoint contract accepts only explicit JUnit jobs on Java25."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_grading_job as fixtures
grader=fixtures.grader
ROOT=fixtures.ROOT
class EntrypointTests(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 run_job=fixtures.JUnitJob.run_job
 def test_source_traversal_is_configuration_error(self):
  self.cfg['sourceFiles']=['../tests/AnswerTest.java']
  with self.assertRaises(grader.GraderError):self.run_job()
 def test_legacy_course_main_descriptor_is_rejected(self):
  self.cfg['mainClass']='Checks'
  with self.assertRaises(grader.GraderError):self.run_job()
 def test_symlink_submission_is_not_gradable(self):
  p=self.job/'student/Student.java';p.unlink();p.symlink_to('/etc/hosts');self.assertFalse(self.run_job()['gradable'])
 def test_cli_writes_standard_pl_results(self):
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  p=subprocess.run([os.sys.executable,str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(self.job)],capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr);r=json.loads((self.job/'results/results.json').read_text());self.assertEqual(r['score'],1)
 def test_cli_infrastructure_failure_has_no_score(self):
  (self.job/'tests/AnswerTest.java').unlink();(self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  p=subprocess.run([os.sys.executable,str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(self.job)],capture_output=True,text=True)
  self.assertEqual(p.returncode,2);r=json.loads((self.job/'results/results.json').read_text());self.assertTrue(r['grading_error']);self.assertNotIn('score',r)
