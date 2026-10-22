"""Test-only current source assemblies; fictional pins never claim publication."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import gradle_unit_fixtures as fixtures

class RuntimeTestViews(unittest.TestCase):
 def test_source_tree_has_four_exact_closures_without_mutating_source(self):
  original=(fixtures.ROOT/'runtime-profiles.json').read_bytes()
  with fixtures.platform_tree() as root:
   value=json.loads((root/'runtime-profiles.json').read_text())
   self.assertEqual(len(value['profiles']),4)
   spec=importlib.util.spec_from_file_location('view_jobs',root/'tools/grading_job.py');jobs=importlib.util.module_from_spec(spec);spec.loader.exec_module(jobs)
   for name,row in value['profiles'].items():
    self.assertTrue(row['image'].startswith('unit.invalid/'))
    self.assertTrue(jobs.runtime_evidence(name,value)['dependencyHashes'])
   self.assertEqual(hashlib.sha256((root/'images/java25-grader/grade.py').read_bytes()).hexdigest(),hashlib.sha256((fixtures.ROOT/'images/java25-grader/grade.py').read_bytes()).hexdigest())
   self.assertEqual((root/'runtime/gradle-jar-v1/toolchain-lock.json').read_bytes(),(fixtures.ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').read_bytes())
   extra=root/'runtime/java25-junit-v1/UNREGISTERED.jar';extra.write_bytes(b'unit extra')
   with self.assertRaisesRegex(jobs.JobError,'closure changed'):jobs.runtime_evidence('java25-junit-v1',value)
  self.assertEqual((fixtures.ROOT/'runtime-profiles.json').read_bytes(),original)
 def test_actual_view_refuses_fictional_execution_image_identity(self):
  with self.assertRaises(ValueError):
   with fixtures.platform_tree(java_image='unit.invalid/synthetic-fixture@sha256:'+'1'*64):pass

if __name__=='__main__':unittest.main()
