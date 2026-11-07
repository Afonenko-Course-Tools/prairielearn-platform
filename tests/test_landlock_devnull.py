"""C syscall fixtures: отрицательные policy проверки, не kernel sandbox proof."""
import json
from typing import ClassVar, TypeGuard
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def _object(value: object) -> TypeGuard[dict[object,object]]:
 return isinstance(value,dict)


def _fixture_record(value: object) -> TypeGuard[dict[str,int]]:
 return _object(value) and all(isinstance(key,str) and type(item) is int for key,item in value.items())


class DevNullSourceTests(unittest.TestCase):
 temp: ClassVar[tempfile.TemporaryDirectory[str]]
 binary: ClassVar[Path]
 @classmethod
 def setUpClass(cls) -> None:
  cls.temp=tempfile.TemporaryDirectory();cls.binary=Path(cls.temp.name)/'fixture'
  p=subprocess.run(['/usr/bin/gcc','-std=c11','-O2','-Wall','-Wextra',str(ROOT/'tests/landlock_devnull_fixture.c'),'-o',str(cls.binary)],capture_output=True,text=True,timeout=20)
  if p.returncode:raise AssertionError(p.stderr)
 @classmethod
 def tearDownClass(cls) -> None:cls.temp.cleanup()
 def run_fixture(self,scenario: int,abi: int=3) -> dict[str,int]:
  p=subprocess.run([str(self.binary),str(scenario),str(abi)],capture_output=True,text=True,timeout=3);self.assertEqual(p.returncode,0,p.stderr)
  value: object=json.loads(p.stdout)
  if not _fixture_record(value):
   raise AssertionError('C fixture должен вернуть целочисленные поля')
  return value
 def test_exact_leaf_gets_only_supported_file_rights_and_no_fd_leak(self) -> None:
  for abi in (1,2,3):
   with self.subTest(abi=abi):
    r=self.run_fixture(0,abi);self.assertEqual(r['executed'],1);self.assertEqual(r['leafRules'],1);self.assertEqual(r['badFlags'],0)
    self.assertEqual(r['allowed'],(1<<1)|(1<<2)|((1<<14) if abi>=3 else 0));self.assertEqual(r['closedFDs']&((1<<6)|(1<<7)|(1<<8)),(1<<6)|(1<<7)|(1<<8))
 def test_wrong_objects_identity_and_syscall_failures_never_exec(self) -> None:
  for scenario in range(1,26):
   with self.subTest(scenario=scenario):
    r=self.run_fixture(scenario);self.assertEqual(r['executed'],0);self.assertEqual(r['leakedFDs'],0)
