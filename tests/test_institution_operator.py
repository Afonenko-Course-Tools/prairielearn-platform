"""Локальный operator отвергает конфигурацию до импорта native dependencies."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class InstitutionOperatorTests(unittest.TestCase):
    def setUp(self):
        self.script=ROOT/'tools/bootstrap-native-course.mjs'
        self.assertTrue(self.script.is_file(),'Native institution operator is missing')
    def test_help_does_not_need_database_or_credentials(self):
        result=subprocess.run(['node',str(self.script),'--help'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--registry',result.stdout)
    def test_unknown_institution_precedes_native_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            registry={'schema':'pl-courses-v2','courses':[{'id':'course-a','institution':'unknown','repository':'https://example.test/native.git','commit':'a'*40,'mount':'/course'}]}
            (path/'registry.json').write_text(json.dumps(registry))
            result=subprocess.run(['node',str(self.script),'--registry',str(path/'registry.json'),'--course-key','course-a','--path','/course/course-a/'+'f'*64],env={**os.environ,'PL_ROOT':str(path/'no-native')},capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Unknown institution key',result.stderr)
            self.assertNotIn('Cannot find package',result.stderr)
