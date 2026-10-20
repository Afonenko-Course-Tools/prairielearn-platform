"""Все профили общего Java runner должны замыкаться на реальные исходники."""
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from grading_job import load_runtime_registry,runtime_evidence
class RuntimeClosure(unittest.TestCase):
 def test_each_declared_profile_matches_current_dependency_bytes(self):
  for runtime in load_runtime_registry()['profiles']:
   with self.subTest(runtime=runtime):self.assertTrue(runtime_evidence(runtime)['dependencyHashes'])
