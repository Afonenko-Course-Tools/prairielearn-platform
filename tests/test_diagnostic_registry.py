import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_check_course as checks
import test_build_course as builds
from gradle_unit_fixtures import registry as unit_registry
ROOT=Path(__file__).resolve().parents[1]

class DiagnosticRegistry(unittest.TestCase):
 def test_explicit_registry_selects_candidate_and_host_runner_consistently(self):
  m=checks.InventoryTests().module();registry=unit_registry();registry['profiles']['java25-junit-v1']['image']=None
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);project=root/'tasks/p';project.mkdir(parents=True)
   files={'S.java':'class S{}','T.java':'class T{}'}
   for name,text in files.items():(project/name).write_text(text)
   def selection(name):return {'projectRelativePath':name,'submissionRelativePath':name,'sha256':hashlib.sha256((project/name).read_bytes()).hexdigest()}
   fact={'qualifiedId':'demo/exr-a','projectRoot':'p','check':{'runtime':'java25-junit-v1'},'sources':[selection('S.java')],'trustedTests':[selection('T.java')]}
   manifest={'schemaVersion':1,'bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[fact]}
   with patch.dict('os.environ',{'PL_LOCAL_IMAGE_ID':'sha256:'+'d'*64}):
    default=m.prepare_job(manifest,root,'demo/exr-a','starter')
    self.assertEqual(default['imageDigest'],m.load_runtime_registry()['profiles']['java25-junit-v1']['image'])
    __import__('shutil').rmtree(default.root)
    job=m.prepare_job(manifest,root,'demo/exr-a','starter',registry=registry)
   try:
    self.assertEqual(job['imageDigest'],'sha256:'+'d'*64)
    with patch.object(m,'load_runtime_registry',side_effect=AssertionError('Explicit registry must not reload defaults')):
     with patch.object(m,'runtime_evidence',return_value={'candidate':'closure'}):
      with patch.object(m.importlib.util,'spec_from_file_location',side_effect=OSError('mock host unavailable')):
       result=m.run_job(job,'host',registry=registry)
       self.assertEqual(result['classification'],'infrastructure-failure')
   finally:__import__('shutil').rmtree(job.root)
 def test_builder_forwards_explicit_candidate_flag(self):
  import inspect
  self.assertIn('candidate_image',inspect.signature(builds.builder.build_course).parameters)
  with patch.object(builds.builder,'git',return_value=''):
   with tempfile.TemporaryDirectory() as d:
    root=Path(d);source=root/'source';entry=source/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts';entry.parent.mkdir(parents=True);entry.write_text('// owner')
    def git(path,*args):return 'https://example.test/source.git' if args==('remote','get-url','origin') else 'abc' if args==('rev-parse','HEAD') else ''
    with patch.object(builds.builder,'git',side_effect=git),patch.object(builds.builder.subprocess,'run',side_effect=OSError('stop after capture')) as run:
     with self.assertRaises(builds.builder.BuildError):builds.builder.build_course(source,'tasks','pilot',root/'out',root/'registry.json','sha256:'+'d'*64)
    command=run.call_args.args[0]
    self.assertEqual(command[command.index('--candidate-image')+1],'sha256:'+'d'*64)
 def test_check_cli_threads_one_explicit_registry_through_prepare_execute_and_receipt(self):
  import sys
  from types import SimpleNamespace
  sys.path.insert(0,str(ROOT/'tools'))
  spec=importlib.util.spec_from_file_location('diagnostic_check',ROOT/'tools/check-course.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'manifest.json').write_text('{}');(root/'registry.json').write_text('{"profiles":{"diagnostic":{}}}')
   registry={'profiles':{'diagnostic':{}}};project={'qualifiedId':'demo/exr-a','projectRoot':'p','check':{'runtime':'diagnostic'}}
   job={'expectations':{}};jobtype=type('Job',(dict,),{});job=jobtype(job);job.root=root/'job';job.root.mkdir()
   args=['check-course.py','--manifest',str(root/'manifest.json'),'--snapshot',str(root),'--runtime-registry',str(root/'registry.json'),'--output',str(root/'result.json')]
   with patch.object(sys,'argv',args),patch.object(cli,'inventory',return_value=[project]),patch.object(cli,'scenario_inventory',return_value=[{'qualifiedId':'demo/exr-a','scenario':'starter'}]),patch.object(cli,'prepare_job',return_value=job) as prepare,patch.object(cli,'run_job',return_value={}) as execute,patch.object(cli,'verify_results',return_value={'exitCode':0}) as receipt:
    self.assertEqual(cli.main(),0)
   self.assertEqual(prepare.call_args.args[-1],registry);self.assertEqual(execute.call_args.args[-1],registry);self.assertEqual(receipt.call_args.args[-1],registry)
