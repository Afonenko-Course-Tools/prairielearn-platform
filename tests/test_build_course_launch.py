"""Синтетическая orchestration: inert C boundary, не actual C/P qualification."""
from pathlib import Path
import importlib.util
import json
import os
import stat
import shutil
import fcntl
import subprocess
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('launch_builder',ROOT/'tools/build-course.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class LaunchContract(unittest.TestCase):
 scratch_parent=None
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='platform252-unit-',dir=self.scratch_parent);self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir();self.owner=self.source/'tasks';self.entry=self.owner/'_extensions/course-prairielearn/entrypoints/export-course.ts';self.entry.parent.mkdir(parents=True);self.entry.write_text('// INERT UNIT never executed\n')
  for args in [('init','-q'),('config','user.name','UNIT'),('config','user.email','unit@example.invalid'),('remote','add','origin','https://example.invalid/source.git'),('add','.'),('commit','-qm','UNIT')]:subprocess.run(['git',*args],cwd=self.source,check=True)
  self.output=self.root/'native-output';self.stage=self.root/'known-stage';self.registry=self.root/'registry.json';self.registry.write_text('{}')
  self.calls=[];self.original_run=subprocess.run
 def run_spy(self,args,*a,**kw):
  if args[0]=='quarto':
   self.calls.append((args,kw));raise subprocess.CalledProcessError(73,args)
  return self.original_run(args,*a,**kw)
 def call(self,**kw):
  with patch('subprocess.run',self.run_spy):
   return builder.build_course(self.source,'tasks','test',self.output,runtime_registry=self.registry,**kw)
 def test_first_child_has_absolute_installed_entry_and_owner_cwd(self):
  with self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed'):self.call()
  self.assertEqual(len(self.calls),1)
  args,kw=self.calls[0];self.assertEqual(args[2],str(self.entry));self.assertEqual(kw['cwd'],self.owner)
  self.assertEqual(args[3],str(self.source));self.assertEqual(args[-2:],['--book','tasks'])
 def test_explicit_stage_literal_is_selected_before_child_and_removed_after_failure(self):
  with self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed'):self.call(export_stage=self.stage)
  self.assertEqual(len(self.calls),1);args,_=self.calls[0]
  self.assertEqual(args[4],str(self.stage/'native'));self.assertEqual(args[args.index('--checks-output')+1],str(self.stage/'checks.json'))
  self.assertFalse(self.stage.exists());self.assertFalse(self.output.exists())


 def emit_package(self,args,*a,**kw):
  if args[0]!='quarto':return self.original_run(args,*a,**kw)
  self.calls.append((args,kw))
  from test_delivery5 import Delivery5 as DeliveryPackage
  fixture=DeliveryPackage();fixture.setUp()
  try:
   native=Path(args[4]);shutil.copytree(fixture.root,native)
   (native/'delivery.json').write_text(json.dumps(fixture.d))
   Path(args[args.index('--checks-output')+1]).write_text(json.dumps({'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','projects':[]}))
  finally:fixture.doCleanups()
  return subprocess.CompletedProcess(args,0)


 def test_namespaced_exporter_and_foreign_caller_cwd(self):
  target=self.owner/'_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export-course.ts'
  target.parent.mkdir(parents=True);self.entry.rename(target);self.entry=target
  subprocess.run(['git','add','-A'],cwd=self.source,check=True);subprocess.run(['git','commit','-qm','namespace'],cwd=self.source,check=True)
  cwd=Path.cwd()
  try:
   os.chdir(self.root)
   with self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  finally:os.chdir(cwd)
  self.assertEqual(self.calls[0][0][2],str(target));self.assertEqual(self.calls[0][1]['cwd'],self.owner)
 def test_default_random_stage_is_private_and_cleans_after_spawn_oserror(self):
  def spawn(args,*a,**kw):
   if args[0]!='quarto':return self.original_run(args,*a,**kw)
   stage=Path(args[4]).parent;self.assertTrue(stage.name.startswith('.pl-export-'));self.assertEqual(stage.parent,self.root)
   self.assertEqual(stat.S_IMODE(stage.stat().st_mode),0o700);self.calls.append(stage);raise OSError('SPAWN_UNIT')
  self.run_spy=spawn
  with self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed'):self.call()
  self.assertFalse(self.calls[0].exists())
 def test_existing_stage_objects_are_never_reused_or_removed(self):
  cases=['empty','nonempty','file','live-link','dangling-link']
  for kind in cases:
   with self.subTest(kind=kind):
    if kind in ['empty','nonempty']:self.stage.mkdir();(self.stage/'keep').write_text('FOREIGN') if kind=='nonempty' else None
    elif kind=='file':self.stage.write_text('FOREIGN')
    else:self.stage.symlink_to(self.source if kind=='live-link' else self.root/'missing')
    with self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=self.stage)
    self.assertFalse(self.calls)
    if self.stage.is_symlink()or self.stage.is_file():self.stage.unlink()
    else:
     if kind=='nonempty':self.assertEqual((self.stage/'keep').read_text(),'FOREIGN');(self.stage/'keep').unlink()
     self.stage.rmdir()
 def test_stage_alias_overlap_and_different_parent_refuse_before_child(self):
  for path in [str(self.stage)+'/../alias',str(self.root)+'/./alias','relative',self.output,self.output.with_name(self.output.name+'-checks.json'),self.source,self.source/'tasks/stage',self.root/'missing/stage']:
   with self.subTest(path=str(path)),self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=path)
  self.assertFalse(self.calls)






class WorkspaceLaunchContract(LaunchContract):
 # Тот же lifecycle на файловой системе checkout, а не только /tmp.
 scratch_parent=ROOT.parent
 def test_actual_cli_success_cleans_fresh_stage_after_producer_exit0(self):
  from test_delivery5 import Delivery5 as DeliveryPackage
  fixture=DeliveryPackage();fixture.setUp()
  try:
   payload=self.root/'payload';shutil.copytree(fixture.root,payload)
   (payload/'delivery.json').write_text(json.dumps(fixture.d))
   checks=self.root/'checks.json';checks.write_text(json.dumps({'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','projects':[]}))
  finally:fixture.doCleanups()
  binary=self.root/'bin';binary.mkdir();spy=binary/'quarto'
  spy.write_text('#!'+sys.executable+' -B\nimport shutil,sys\nshutil.copytree('+repr(str(payload))+',sys.argv[4])\nshutil.copyfile('+repr(str(checks))+',sys.argv[sys.argv.index("--checks-output")+1])\n');spy.chmod(0o755)
  env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}
  result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/build-course.py'),'--source',str(self.source),'--book','tasks','--instance','test','--output',str(self.output),'--runtime-registry',str(self.registry),'--export-stage',str(self.stage)],cwd=self.root,env=env,capture_output=True,timeout=15)
  self.assertEqual(result.returncode,0,result.stderr)
  self.assertTrue((self.output/'delivery.json').is_file());self.assertTrue(self.output.with_name(self.output.name+'-checks.json').is_file());self.assertFalse(self.stage.exists())

if __name__=='__main__':unittest.main()
