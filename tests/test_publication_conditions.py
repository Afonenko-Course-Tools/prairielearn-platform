"""Только parser/consumer boundary; exporter subprocess никогда не исполняется."""
import hashlib,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('builder195',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
class PublicationConditions(unittest.TestCase):
 def test_actual_cli_parser_forwards_optional_dependency(self):
  with patch.object(sys,'argv',['build-course.py','--source','/source','--instance','pilot','--output','/new','--publication-conditions','/conditions.json']),patch.object(builder,'build_course') as call:
   builder.main();self.assertEqual(call.call_args.args[-1],Path('/conditions.json'))
 def test_optional_dependency_forwarded_before_any_export(self):
  class ReachedExporter(Exception):pass
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source';source.mkdir()
   for args in [['init','-q'],['remote','add','origin','https://example.invalid/course.git']]:subprocess.run(['git',*args],cwd=source,check=True,capture_output=True)
   entry=source/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts';entry.parent.mkdir(parents=True);entry.write_text('// fixture only; never executed')
   subprocess.run(['git','add','.'],cwd=source,check=True,capture_output=True);subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Fixture'],cwd=source,check=True,capture_output=True)
   archive=root/'conditions.zip';archive.write_bytes(b'fixture bytes');receipt=root/'publication.json';receipt.write_text('{}')
   typed=lambda p:{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
   manifest=root/'conditions.json';manifest.write_text(json.dumps({'schema':'pl-publication-conditions-v1','publication':{'receipt':typed(receipt)},'archives':[{'file':typed(archive)}]}))
   original=builder.subprocess.run
   def intercept(command,*args,**kwargs):
    if command[0]=='quarto':
     self.assertEqual(command[-2:],['--publication-conditions',str(manifest)]);raise ReachedExporter()
    return original(command,*args,**kwargs)
   with patch.object(builder._assembly,'for_build',return_value=None),patch.object(builder.subprocess,'run',side_effect=intercept):
    with self.assertRaises(ReachedExporter):builder.build_course(source,'tasks','pilot',root/'new',publication_conditions=manifest)
   self.assertFalse((root/'new').exists())
 def test_external_dependency_drift_rejected_by_boundary_snapshot(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);archive=root/'a.zip';archive.write_bytes(b'archive');proof=root/'proof.json';proof.write_text('{}')
   typed=lambda p:{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
   manifest=root/'conditions.json';manifest.write_text(json.dumps({'schema':'pl-publication-conditions-v1','publication':{'receipt':typed(proof)},'archives':[{'file':typed(archive)}]}))
   before=builder.publication_conditions_snapshot(manifest);archive.write_bytes(b'DRIFT')
   with self.assertRaises((builder.BuildError,OSError)):self.assertEqual(builder.publication_conditions_snapshot(manifest),before)
