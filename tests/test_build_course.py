"""Builder uses installed full exporter and preserves fresh candidate semantics."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
class BuilderContract(unittest.TestCase):
 def test_existing_output_is_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir();out=root/'out';out.mkdir();(out/'sentinel').write_text('keep')
   with self.assertRaises(builder.BuildError):builder.build_course(source,'tasks','pilot',out)
   self.assertEqual((out/'sentinel').read_text(),'keep')
 def test_old_shell_exporter_cannot_build(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir()
   for cmd in [['git','init','-q'],['git','config','user.name','Synthetic'],['git','config','user.email','synthetic@example.test'],['git','remote','add','origin','https://example.test/source.git']]:subprocess.run(cmd,cwd=source,check=True)
   p=source/'tasks/_extensions/course-prairielearn/entrypoints/export.ts';p.parent.mkdir(parents=True);p.write_text('// old exporter')
   subprocess.run(['git','add','.'],cwd=source,check=True);subprocess.run(['git','commit','-qm','Fixture'],cwd=source,check=True)
   with self.assertRaises(builder.BuildError):builder.build_course(source,'tasks','pilot',root/'out')
   self.assertFalse((root/'out').exists())
 def test_atomic_publication_does_not_overwrite_concurrent_directory(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'from';source.mkdir();target=root/'target';target.mkdir();(target/'keep').write_text('keep')
   with self.assertRaises(builder.BuildError):builder.publish_directory(source,target)
   self.assertEqual((target/'keep').read_text(),'keep')
 def test_full_exporter_generates_fresh_candidate_and_private_checks(self):
  import json,os
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir();binary=root/'bin';binary.mkdir()
   for cmd in [['git','init','-q'],['git','config','user.name','Synthetic'],['git','config','user.email','synthetic@example.test'],['git','remote','add','origin','https://example.test/source.git']]:subprocess.run(cmd,cwd=source,check=True)
   entry=source/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts';entry.parent.mkdir(parents=True);entry.write_text('// installed full exporter boundary')
   subprocess.run(['git','add','.'],cwd=source,check=True);subprocess.run(['git','commit','-qm','Fixture'],cwd=source,check=True)
   (binary/'quarto').write_text('''#!/usr/bin/env python3
import json,pathlib,sys
assert sys.argv[1]=='run' and sys.argv[2].endswith('export-course.ts')
assert sys.argv[5:7]==['--instance','pilot']
out=pathlib.Path(sys.argv[4]);out.mkdir();checks=pathlib.Path(sys.argv[8])
(out/'infoCourse.json').write_text(json.dumps({'name':'SYN'}))
q=out/'questions/synthetic/exr-a';q.mkdir(parents=True)
(q/'info.json').write_text(json.dumps({'uuid':'00000000-0000-4000-8000-000000000001'}))
(q/'question.html').write_text('Synthetic condition')
delivery={'schemaVersion':1,'deliveryHash':'c'*64,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'questions':['synthetic/exr-a']}
(out/'delivery.json').write_text(json.dumps(delivery));checks.write_text(json.dumps({'schemaVersion':1,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[]}))
''');(binary/'quarto').chmod(0o755)
   output=root/'candidate'
   with patch.dict(os.environ,{'PATH':str(binary)+os.pathsep+os.environ['PATH']}):builder.build_course(source,'tasks','pilot',output)
   self.assertTrue((output/'questions/synthetic/exr-a/info.json').is_file());self.assertTrue((root/'candidate-checks.json').is_file());self.assertFalse((output/'checks.json').exists())
   p=json.loads((output/'provenance.json').read_text());self.assertEqual(p['deliveryHash'],'c'*64);self.assertEqual(p['source']['dirty'],False)
