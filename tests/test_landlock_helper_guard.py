"""Source guard regression; mocked container facts не доказывают изоляцию."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_grading_job import grader

class InstalledHelperGuardTests(unittest.TestCase):
 def test_unmatched_installed_helper_refuses_before_first_child(self):
  with tempfile.TemporaryDirectory() as temporary:
   job=Path(temporary)
   for name in ('student','tests'):(job/name).mkdir()
   real_iterdir=Path.iterdir
   def directories(path):return iter([Path('/sys/class/net/lo')]) if path==Path('/sys/class/net') else real_iterdir(path)
   with patch.dict(os.environ,PL_CONTAINMENT='official'),patch.object(os,'geteuid',return_value=0),patch.object(Path,'is_file',return_value=True),patch.object(Path,'iterdir',directories),patch.object(grader.shutil,'which',return_value='/usr/sbin/runuser'),patch.object(grader,'_protect_input_identity'),patch('pwd.getpwnam',return_value=SimpleNamespace(pw_uid=1001)),patch.object(grader,'_run',return_value=(0,'1001\n',None)) as child:
    with self.assertRaisesRegex(grader.GraderError,'Landlock helper'):grader._native_containment(job,[])
    child.assert_not_called()
