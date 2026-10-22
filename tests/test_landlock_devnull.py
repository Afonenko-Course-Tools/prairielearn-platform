"""C syscall fixtures: отрицательные policy проверки, не kernel sandbox proof."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class DevNullSourceTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.binary=Path(cls.temp.name)/'fixture'
  p=subprocess.run(['/usr/bin/gcc','-std=c11','-O2','-Wall','-Wextra',str(ROOT/'tests/landlock_devnull_fixture.c'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=20)
  if p.returncode:raise AssertionError(p.stderr)
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def run_fixture(self,scenario,abi=3):
  p=subprocess.run([str(self.binary),str(scenario),str(abi)],capture_output=True,text=True,timeout=3);self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
 def test_exact_leaf_gets_only_supported_file_rights_and_no_fd_leak(self):
  for abi in (1,2,3):
   with self.subTest(abi=abi):
    r=self.run_fixture(0,abi);self.assertEqual(r['executed'],1);self.assertEqual(r['leafRules'],1);self.assertEqual(r['badFlags'],0)
    self.assertEqual(r['allowed'],(1<<1)|(1<<2)|((1<<14) if abi>=3 else 0));self.assertEqual(r['closedFDs']&((1<<6)|(1<<7)|(1<<8)),(1<<6)|(1<<7)|(1<<8))
 def test_wrong_objects_identity_and_syscall_failures_never_exec(self):
  for scenario in range(1,26):
   with self.subTest(scenario=scenario):
    r=self.run_fixture(scenario);self.assertEqual(r['executed'],0);self.assertEqual(r['leakedFDs'],0)
