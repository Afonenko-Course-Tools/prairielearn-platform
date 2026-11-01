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
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='platform252-unit-');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir();self.owner=self.source/'tasks';self.entry=self.owner/'_extensions/course-prairielearn/entrypoints/export-course.ts';self.entry.parent.mkdir(parents=True);self.entry.write_text('// INERT UNIT never executed\n')
  for args in [('init','-q'),('config','user.name','UNIT'),('config','user.email','unit@example.invalid'),('remote','add','origin','https://example.invalid/source.git'),('add','.'),('commit','-qm','UNIT')]:subprocess.run(['git',*args],cwd=self.source,check=True)
  self.output=self.root/'native-output';self.stage=self.root/'known-stage';self.registry=self.root/'registry.json';self.registry.write_text('{}')
  self.calls=[];self.original_run=subprocess.run
 def run_spy(self,args,*a,**kw):
  if args[0]=='quarto':
   self.calls.append((args,kw));raise subprocess.CalledProcessError(73,args)
  return self.original_run(args,*a,**kw)
 def call(self,**kw):
  with patch('subprocess.run',self.run_spy),patch.object(builder._assembly,'for_build',return_value=None):
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
  from test_delivery_verification import DeliveryPackage
  fixture=DeliveryPackage();fixture.setUp()
  try:
   native=Path(args[4]);shutil.copytree(fixture.root,native)
   (native/'delivery.json').write_text(json.dumps(fixture.delivery))
   Path(args[args.index('--checks-output')+1]).write_text(json.dumps(fixture.checks))
  finally:fixture.doCleanups()
  return subprocess.CompletedProcess(args,0)
 def test_private_checks_replacement_before_publication_refuses_and_preserves_foreign(self):
  self.run_spy=self.emit_package;original=builder.tree;replaced=False
  def swap(native):
   nonlocal replaced
   result=original(native);target=self.output.with_name(self.output.name+'-checks.json')
   if target.exists() and not replaced:
    target.rename(self.root/'our-checks');target.write_text('FOREIGN');replaced=True
   return result
  with patch.object(builder,'tree',swap),self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  self.assertEqual(self.output.with_name(self.output.name+'-checks.json').read_text(),'FOREIGN')
  self.assertFalse(self.output.exists())
 def test_exception_after_native_rename_preserves_both_published_outputs(self):
  self.run_spy=self.emit_package;original=builder.publish_directory
  def stop_after(*a,**kw):original(*a,**kw);raise OSError('AFTER_ATOMIC_PUBLICATION')
  with patch.object(builder,'publish_directory',stop_after),self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  self.assertTrue((self.output/'provenance.json').is_file())
  self.assertTrue(self.output.with_name(self.output.name+'-checks.json').is_file())


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
   stage=Path(args[4]).parent;self.assertTrue(stage.name.startswith('.pl-full-export-'));self.assertEqual(stage.parent,self.root)
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
 def test_registry_inside_stage_and_symlink_output_parent_refuse(self):
  self.registry=self.stage/'registry.json'
  with self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  self.registry=self.root/'registry.json';alias=self.root/'alias';alias.symlink_to(self.root)
  self.output=alias/'out'
  with self.assertRaises(builder.BuildError):self.call(export_stage=alias/'stage')
  self.assertFalse(self.calls)
 def test_installed_entry_parent_alias_is_not_an_installed_owner(self):
  target=self.owner/'_extensions/course-prairielearn';target.rename(self.owner/'physical')
  target.symlink_to(self.owner/'physical',target_is_directory=True)
  subprocess.run(['git','add','-A'],cwd=self.source,check=True);subprocess.run(['git','commit','-qm','alias'],cwd=self.source,check=True)
  with self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  self.assertFalse(self.calls)
 def test_creation_collision_preserves_foreign_stage(self):
  original=os.mkdir
  def collision(name,*a,**kw):
   if name==self.stage.name and kw.get('dir_fd')is not None:
    original(self.stage);(self.stage/'keep').write_text('FOREIGN')
   return original(name,*a,**kw)
  with patch.object(os,'mkdir',collision),self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=self.stage)
  self.assertEqual((self.stage/'keep').read_text(),'FOREIGN');self.assertFalse(self.calls)
 def test_parent_lock_blocks_second_builder_until_cleanup(self):
  fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=self.stage)
   self.assertFalse(self.calls);self.assertFalse(self.stage.exists())
  finally:os.close(fd)
 def test_stage_replacement_keeps_primary_child_error_and_foreign_bytes(self):
  original=self.run_spy
  def replace(args,*a,**kw):
   if args[0]=='quarto':
    self.stage.rename(self.root/'old-stage');self.stage.mkdir();(self.stage/'keep').write_text('FOREIGN')
   return original(args,*a,**kw)
  self.run_spy=replace
  with self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed')as caught:self.call(export_stage=self.stage)
  self.assertIn('cleanup refused',' '.join(caught.exception.__notes__).lower());self.assertEqual((self.stage/'keep').read_text(),'FOREIGN')
 def test_cleanup_uses_retained_fd_even_if_name_replaced_after_entry_guard(self):
  original=os.listdir;swapped=False
  def barrier(fd):
   nonlocal swapped
   if isinstance(fd,int)and not swapped:
    self.stage.rename(self.root/'old-stage');self.stage.mkdir();(self.stage/'keep').write_text('FOREIGN');swapped=True
   return original(fd)
  with patch.object(os,'listdir',barrier),self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed'):self.call(export_stage=self.stage)
  self.assertTrue(swapped);self.assertEqual((self.stage/'keep').read_text(),'FOREIGN')
 def test_parent_replacement_during_child_is_detected_and_not_cleaned_by_new_path(self):
  original=self.run_spy;aside=self.root.with_name(self.root.name+'-old');self.addCleanup(lambda:shutil.rmtree(aside,ignore_errors=True))
  def replace(args,*a,**kw):
   if args[0]=='quarto':
    self.root.rename(aside);self.root.mkdir();self.stage.mkdir();(self.stage/'keep').write_text('FOREIGN')
   return original(args,*a,**kw)
  self.run_spy=replace
  with self.assertRaisesRegex(builder.BuildError,'Installed full owner export failed')as caught:self.call(export_stage=self.stage)
  self.assertIn('parent identity changed',' '.join(caught.exception.__notes__).lower());self.assertEqual((self.stage/'keep').read_text(),'FOREIGN')
 def test_successful_synthetic_package_runs_real_tail_and_keeps_checks_private(self):
  self.run_spy=self.emit_package;self.call(export_stage=self.stage)
  self.assertFalse(self.stage.exists());self.assertFalse((self.output/'checks.json').exists())
  provenance=json.loads((self.output/'provenance.json').read_text());self.assertFalse(provenance['source']['dirty'])
  self.assertTrue(self.output.with_name(self.output.name+'-checks.json').is_file())
 def test_final_destination_collision_preserves_foreign_empty_directory(self):
  self.run_spy=self.emit_package;original=builder.publish_directory
  def collide(*a,**kw):self.output.mkdir();return original(*a,**kw)
  with patch.object(builder,'publish_directory',collide),self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
  self.assertTrue(self.output.is_dir());self.assertEqual(list(self.output.iterdir()),[])
  self.assertFalse(self.output.with_name(self.output.name+'-checks.json').exists())
 def test_native_and_checks_identity_replacements_before_tail_publication_refuse(self):
  original=builder.write_json
  for name in ['native','checks.json']:
   with self.subTest(name=name):
    self.run_spy=self.emit_package
    def swap(path,value):
     original(path,value);target=self.stage/name;target.rename(self.root/('old-'+name))
     if name=='native':shutil.copytree(self.root/('old-'+name),target)
     else:shutil.copyfile(self.root/('old-'+name),target)
    with patch.object(builder,'write_json',swap),self.assertRaises(builder.BuildError):self.call(export_stage=self.stage)
    self.assertFalse(self.output.exists())
 def test_source_mutation_and_invalid_missing_package_do_not_publish(self):
  for kind in ['source','invalid','missing']:
   with self.subTest(kind=kind):
    def emit(args,*a,**kw):
     result=self.emit_package(args,*a,**kw)
     if args[0]=='quarto':
      if kind=='source':(self.source/'drift').write_text('changed')
      elif kind=='invalid':(Path(args[4])/'infoCourse.json').write_text('{}')
      else:shutil.rmtree(Path(args[4]))
     return result
    self.run_spy=emit
    with self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=self.stage)
    self.assertFalse(self.output.exists());self.assertFalse(self.stage.exists())
    if kind=='source':(self.source/'drift').unlink()
 def test_cleanup_error_after_success_reports_published_outcome_without_removing_outputs(self):
  self.run_spy=self.emit_package
  with patch.object(builder._ExportStage,'_clear_directory',side_effect=OSError('CLEANUP_UNIT')),self.assertRaisesRegex(builder.BuildError,'published=True'):self.call(export_stage=self.stage)
  self.assertTrue((self.output/'provenance.json').exists());self.assertTrue(self.output.with_name(self.output.name+'-checks.json').exists())
 def test_cancellation_keeps_primary_and_releases_parent_lock(self):
  def cancel(args,*a,**kw):
   if args[0]=='quarto':raise KeyboardInterrupt('CANCEL_UNIT')
   return self.original_run(args,*a,**kw)
  self.run_spy=cancel
  with self.assertRaisesRegex(KeyboardInterrupt,'CANCEL_UNIT'):self.call(export_stage=self.stage)
  self.assertFalse(self.stage.exists())
  self.run_spy=self.emit_package;self.call(export_stage=self.stage)


 def test_cli_external_inert_spy_observes_real_process_cwd_argv_and_deferral(self):
  binary=self.root/'bin';binary.mkdir();log=self.root/'child.json';spy=binary/'quarto'
  spy.write_text('#!'+sys.executable+' -B\nimport os,sys,json\nfrom pathlib import Path\nPath('+repr(str(log))+').write_text(json.dumps({"argv":sys.argv,"cwd":os.getcwd(),"defer":os.environ.get("COURSE_SITE_DEFER_DOWNLOADS")}))\nraise SystemExit(73)\n');spy.chmod(0o755)
  env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'COURSE_SITE_DEFER_DOWNLOADS':'1','PYTHONDONTWRITEBYTECODE':'1'}
  result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/build-course.py'),'--source',str(self.source),'--book','tasks','--instance','test','--output',str(self.output),'--runtime-registry',str(self.registry),'--export-stage',str(self.stage)],cwd=self.root,env=env,capture_output=True)
  self.assertEqual(result.returncode,1,result.stderr);self.assertIn(b'Installed full owner export failed',result.stderr)
  seen=json.loads(log.read_text());self.assertEqual(seen['cwd'],str(self.owner));self.assertEqual(seen['argv'][2],str(self.entry));self.assertEqual(seen['argv'][4],str(self.stage/'native'));self.assertEqual(seen['defer'],'1');self.assertFalse(self.stage.exists())
 def test_private_output_existing_symlink_and_both_exporters_refuse(self):
  self.run_spy=self.emit_package;private=self.output.with_name(self.output.name+'-checks.json');target=self.root/'foreign';target.write_text('KEEP');private.symlink_to(target)
  with self.assertRaises((builder.BuildError,OSError)):self.call(export_stage=self.stage)
  self.assertEqual(target.read_text(),'KEEP');self.assertFalse(self.output.exists());private.unlink()
  other=self.owner/'_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export-course.ts';other.parent.mkdir(parents=True);other.write_text('// second')
  subprocess.run(['git','add','.'],cwd=self.source,check=True);subprocess.run(['git','commit','-qm','ambiguous'],cwd=self.source,check=True);self.calls=[]
  with self.assertRaisesRegex(builder.BuildError,'Exactly one'):self.call(export_stage=self.stage)
  self.assertFalse(self.calls)


 def test_fifo_checks_from_child_are_rejected_without_blocking(self):
  binary=self.root/'bin';binary.mkdir();spy=binary/'quarto'
  spy.write_text('#!'+sys.executable+' -B\nimport os,sys\nfrom pathlib import Path\nPath(sys.argv[4]).mkdir()\nos.mkfifo(sys.argv[sys.argv.index("--checks-output")+1])\n');spy.chmod(0o755)
  env={**os.environ,'PATH':str(binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}
  result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/build-course.py'),'--source',str(self.source),'--book','tasks','--instance','test','--output',str(self.output),'--runtime-registry',str(self.registry),'--export-stage',str(self.stage)],cwd=self.root,env=env,capture_output=True,timeout=3)
  self.assertEqual(result.returncode,1,result.stderr);self.assertIn(b'Invalid export product type',result.stderr)
  self.assertFalse(self.output.exists());self.assertFalse(self.stage.exists())

if __name__=='__main__':unittest.main()




