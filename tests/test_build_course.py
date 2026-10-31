"""Builder uses installed full exporter and preserves fresh candidate semantics."""
from gradle_unit_fixtures import write_registry as unit_registry_file
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
   with self.assertRaises(builder.BuildError):builder.build_course(source,'tasks','pilot',out,runtime_registry=unit_registry_file(root))
   self.assertEqual((out/'sentinel').read_text(),'keep')
 def test_old_shell_exporter_cannot_build(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir()
   for cmd in [['git','init','-q'],['git','config','user.name','Synthetic'],['git','config','user.email','synthetic@example.test'],['git','remote','add','origin','https://example.test/source.git']]:subprocess.run(cmd,cwd=source,check=True)
   p=source/'tasks/_extensions/course-prairielearn/entrypoints/export.ts';p.parent.mkdir(parents=True);p.write_text('// old exporter')
   subprocess.run(['git','add','.'],cwd=source,check=True);subprocess.run(['git','commit','-qm','Fixture'],cwd=source,check=True)
   with self.assertRaises(builder.BuildError):builder.build_course(source,'tasks','pilot',root/'out',runtime_registry=unit_registry_file(root))
   self.assertFalse((root/'out').exists())
 def test_atomic_publication_does_not_overwrite_concurrent_directory(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'from';source.mkdir();target=root/'target';target.mkdir();(target/'keep').write_text('keep')
   with self.assertRaises(builder.BuildError):builder.publish_directory(source,target)
   self.assertEqual((target/'keep').read_text(),'keep')
 def test_full_exporter_generates_fresh_candidate_and_private_checks(self):
  # Полный closed3 пакет вместо прежнего незамкнутого UUID-only stub.
  import json
  import test_delivery4_corrections as focused
  helper=focused.BuildReader();helper.setUp();old=focused.legacy.DeliveryPackage();old.setUp()
  try:
   old.put('delivery.json',old.delivery);row=helper.build(old.root,old.delivery,old.checks,'legacy-candidate')
   self.assertTrue(row['accepted'],row);output=helper.root/'legacy-candidate'
   self.assertTrue((output/('questions/'+old.q+'/info.json')).is_file());self.assertTrue((helper.root/'legacy-candidate-checks.json').is_file());self.assertFalse((output/'checks.json').exists())
   provenance=json.loads((output/'provenance.json').read_text());self.assertEqual(provenance['deliveryHash'],old.delivery['deliveryHash']);self.assertFalse(provenance['source']['dirty'])
  finally:old.doCleanups();helper.doCleanups()
