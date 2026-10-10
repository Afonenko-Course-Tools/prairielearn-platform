import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'tools/start-pl.sh'

class StartupContract(unittest.TestCase):
    def run_guard(self, path):
        return subprocess.run(['sh',str(SCRIPT),'sh','-c','printf STARTED'],env={**os.environ,'HOST_JOBS_DIR':path},capture_output=True,text=True)
    def test_relative_jobs_path_is_refused_before_start(self):
        result=self.run_guard('private/jobs')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('STARTED',result.stdout)
        self.assertIn('absolute',result.stderr)
    def test_empty_jobs_path_is_refused_before_start(self):
        result=self.run_guard('')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('STARTED',result.stdout)
    def test_absolute_path_passes_and_command_receives_control(self):
        with tempfile.TemporaryDirectory() as jobs:
            result=self.run_guard(jobs)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'STARTED')
