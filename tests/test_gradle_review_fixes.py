"""R1–R3: отдельные контрпримеры private provenance; Gradle doubles только unit."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_gradle_build as native
from gradle_unit_fixtures import registry

grader=native.grader

class CopiedInputBindingTests(native.NativeArtifactUnitTests):
 def test_copy_window_source_or_recipe_substitution_restore_is_rejected(self):
  for kind in ('source','recipe'):
   with self.subTest(kind=kind):
    self.tmp.cleanup();native.fixtures.JUnitJob.setUp(self)
    target=self.job/'student/Student.java' if kind=='source' else native.ROOT/'runtime/gradle-jar-v1/build.gradle'
    original=Path.read_bytes;reads=0
    def substitute(path):
     nonlocal reads
     data=original(path)
     if path==target:
      reads+=1
      if reads==(3 if kind=='source' else 2):return b'// UNIT ONLY copy-window alternate bytes\n'+data
     return data
    with patch.object(Path,'read_bytes',substitute):
     with self.assertRaises(grader.GraderError):self.build()
    self.assertFalse((self.job/'build').exists())
 def test_unselected_file_cannot_become_part_of_copied_baseline(self):
  original=Path.write_bytes
  def inject(path,data):
   value=original(path,data)
   if path.name=='build.gradle' and path.parent.name.startswith('native-gradle-build-'):
    (path.parent/'src').chmod(0o755)
    original(path.parent/'src/Unselected.java',b'class Unselected {}')
    (path.parent/'src').chmod(0o555)
   return value
  with patch.object(Path,'write_bytes',inject):
   with self.assertRaises(grader.GraderError):self.build()
  self.assertFalse((self.job/'build').exists())

class RecipeMembershipTests(unittest.TestCase):
 def test_omitted_recipe_pins_fail_before_any_java_or_gradle_child(self):
  recipe=('runtime/gradle-jar-v1/build.gradle','runtime/gradle-jar-v1/settings.gradle','runtime/gradle-jar-v1/toolchain-lock.json')
  for missing in [*(tuple([name]) for name in recipe),recipe]:
   with self.subTest(missing=missing):
    value=registry()
    for name in missing:value['profiles']['java25-gradle-junit-v1']['sharedFiles'].pop(name)
    with patch.object(grader,'_run',side_effect=AssertionError('Java child ran before recipe membership admission')):
     with self.assertRaisesRegex(grader.GraderError,'recipe'):grader.preflight('java25-gradle-junit-v1',value)
 def test_complete_native_pins_and_plain_profiles_remain_admissible(self):
  value=registry()
  for rid in ('java25-gradle-junit-v1','java25-junit-v1','java25-mutation-v1'):
   with self.subTest(runtime=rid):self.assertTrue(grader.preflight(rid,value)[2])

class DurableBuildProofTests(native.BuildEvidenceTests):
 def test_rehashed_reference_or_behavior_proof_downgrade_is_rejected(self):
  jobs=self.jobs()
  for scenario in ('reference:default','starter'):
   with self.subTest(scenario=scenario):
    result=self.observation();result['scenario']=scenario
    required=[{'qualifiedId':result['qualifiedId'],'scenario':scenario,'optional':False}]
    receipt=jobs.verify_results([result],{},required,registry=registry())
    row=receipt['buildEvidence'][0];row['status']='not-run'
    for key in ('artifact','inputHash','dependencyHash','durationSeconds'):row.pop(key,None)
    receipt['identityHash']=jobs.digest({k:v for k,v in receipt.items() if k!='identityHash'})
    with self.assertRaises(jobs.JobError):jobs.validate_receipt_integrity(receipt)
 def test_public_execution_requires_successful_same_input_build_proof(self):
  jobs=self.jobs()
  for mutation in ('missing','not-run','input','dependency','execution-missing','execution-drift'):
   with self.subTest(mutation=mutation):
    result=self.observation();public=copy.deepcopy(result)
    for key in ('schemaVersion','scope','backend','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes'):public.pop(key,None)
    if mutation=='missing':public.pop('buildEvidence')
    elif mutation=='not-run':public['buildEvidence']={'schemaVersion':1,'kind':'gradle-jar-v1','status':'not-run'}
    elif mutation=='input':public['buildEvidence']['inputHash']='8'*64
    elif mutation=='dependency':public['buildEvidence']['dependencyHash']='9'*64
    elif mutation=='execution-missing':public.pop('executionEvidence')
    else:public['executionEvidence']['dependencyHash']='0'*64
    result['publicResult']=public
    with self.assertRaises(jobs.JobError):jobs.verify_results([result],{},registry=registry())

class ReceiptOutcomeConsistencyTests(native.BuildEvidenceTests):
 def test_fake_not_run_api_flag_cannot_downgrade_behavior_receipt(self):
  jobs=self.jobs();result=self.observation();required=[{'qualifiedId':result['qualifiedId'],'scenario':result['scenario'],'optional':False}]
  receipt=jobs.verify_results([result],{},required,registry=registry());row=receipt['buildEvidence'][0]
  row['status']='not-run';row['outcome']['apiPrecheck']='not-run'
  for key in ('inputHash','dependencyHash','artifact'):row.pop(key,None)
  receipt['identityHash']=jobs.digest({k:v for k,v in receipt.items() if k!='identityHash'})
  with self.assertRaises(jobs.JobError):jobs.validate_receipt_integrity(receipt)
 def test_unknown_missing_or_inconsistent_outcome_fields_are_rejected(self):
  jobs=self.jobs();result=self.observation();required=[{'qualifiedId':result['qualifiedId'],'scenario':result['scenario'],'optional':False}]
  receipt=jobs.verify_results([result],{},required,registry=registry())
  for mutation in ('missing','unknown','student-stage','trusted-stage','api-stage','dependent-stage'):
   with self.subTest(mutation=mutation):
    forged=copy.deepcopy(receipt);row=forged['buildEvidence'][0]
    if mutation=='missing':row.pop('outcome')
    elif mutation=='unknown':row['outcome']['extra']='untrusted'
    elif mutation=='student-stage':row['outcome']['studentCompilation']='failure'
    elif mutation=='trusted-stage':row['outcome']['trustedCompilation']='not-run'
    elif mutation=='api-stage':row['outcome']['apiPrecheck']='failure'
    else:row['outcome']['dependentExecution']='not-run'
    forged['identityHash']=jobs.digest({k:v for k,v in forged.items() if k!='identityHash'})
    with self.assertRaises(jobs.JobError):jobs.validate_receipt_integrity(forged)

class NegativeAndPublicProofControls(native.BuildEvidenceTests):
 def test_matched_reference_requires_build_even_with_coherent_api_negative_outcome(self):
  jobs=self.jobs();result=self.observation();result['scenario']='reference:default';required=[{'qualifiedId':result['qualifiedId'],'scenario':result['scenario'],'optional':False}]
  receipt=jobs.verify_results([result],{},required,registry=registry());row=receipt['buildEvidence'][0]
  row['status']='not-run';row['outcome']={'classification':'student-api-mismatch','infrastructure':'complete','studentCompilation':'success','trustedCompilation':'not-run','apiPrecheck':'failure','dependentExecution':'not-run'}
  for key in ('inputHash','dependencyHash','artifact'):row.pop(key,None)
  receipt['identityHash']=jobs.digest({k:v for k,v in receipt.items() if k!='identityHash'})
  with self.assertRaisesRegex(jobs.JobError,'Matched reference'):jobs.validate_receipt_integrity(receipt)
 def test_same_input_successful_public_proof_and_plain_receipt_are_valid(self):
  jobs=self.jobs();result=self.observation();public=copy.deepcopy(result)
  for key in ('schemaVersion','scope','backend','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes'):public.pop(key,None)
  result['publicResult']=public;self.assertEqual(jobs.verify_results([result],{},registry=registry())['status'],'success')
  import test_review_receipts as review
  with patch.object(review.g,'load_runtime_registry',registry):plain=review.result()
  receipt=jobs.verify_results([plain],{},registry=registry());self.assertNotIn('buildEvidence',receipt);jobs.validate_receipt_integrity(receipt)
 def test_actual_compile_and_api_negative_rows_keep_honest_not_run(self):
  jobs=self.jobs();fixture=native.fixtures.JUnitJob();fixture.setUp()
  try:
   fixture.cfg.update(runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
   for kind in ('compile','api'):
    if kind=='compile':(fixture.job/'student/Student.java').write_text('not Java')
    else:
     (fixture.job/'student/Student.java').write_text('public class Student {}')
     fixture.cfg['testFiles'].append('ApiContract.java');fixture.cfg['apiPrecheck']={'files':['ApiContract.java'],'entry':'ApiContract'}
     (fixture.job/'tests/ApiContract.java').write_text('import org.prairielearn.api.PlatformApiPrecheck; public class ApiContract {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.method("Student","answer",int.class,9,0);}}')
    (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg));actual=grader.grade(fixture.job,registry=registry())
    model=self.observation();metadata={key:model[key] for key in ('schemaVersion','scope','backend','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes')};metadata.update(backend='host',scenario='contract:'+kind)
    result={**metadata,**actual,'publicResult':copy.deepcopy(actual)}
    expected={result['qualifiedId']+':'+result['scenario']:{'classification':actual['classification'],'student-compilation':actual['studentCompilation'],'job':'complete'}};required=[{'qualifiedId':result['qualifiedId'],'scenario':result['scenario'],'optional':False}]
    receipt=jobs.verify_results([result],expected,required,registry=registry());self.assertEqual(receipt['status'],'success');self.assertEqual(receipt['buildEvidence'][0]['status'],'not-run');self.assertNotIn('artifact',receipt['buildEvidence'][0]);jobs.validate_receipt_integrity(receipt)
  finally:fixture.doCleanups()

class NativePublicSchemaTests(native.BuildEvidenceTests):
 def test_native_public_result_cannot_omit_build_evidence_at_schema_boundary(self):
  jobs=self.jobs();result=self.observation();public=copy.deepcopy(result)
  for key in ('schemaVersion','scope','backend','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes','buildEvidence'):public.pop(key,None)
  result['publicResult']=public
  with self.assertRaises(jobs.JobError):jobs.validate('check-result',result)

class FailedBuildInputBindingTests(unittest.TestCase):
 def test_infrastructure_build_failure_retains_known_selected_input_identity(self):
  fixture=native.fixtures.JUnitJob();fixture.setUp()
  try:
   fixture.cfg.update(runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
   (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg));result=grader.grade(fixture.job,registry=registry())
   import hashlib
   expected=hashlib.sha256(json.dumps({'sources':{'Student.java':hashlib.sha256((fixture.job/'student/Student.java').read_bytes()).hexdigest()},'javaBuild':fixture.cfg['javaBuild']},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
   self.assertEqual(result['buildEvidence'].get('inputHash'),expected)
   self.assertEqual(result['classification'],'infrastructure-failure');self.assertNotIn('artifact',result['buildEvidence']);self.assertNotIn('score',result)
  finally:fixture.doCleanups()

class PublicInfrastructureBoundaryTests(unittest.TestCase):
 def test_public_infrastructure_failure_preserves_primary_build_stage_facts(self):
  """Container subprocess double only: no Docker command executes in this unit."""
  import hashlib,shutil
  from types import SimpleNamespace
  fixture=native.fixtures.JUnitJob();fixture.setUp();model=native.BuildEvidenceTests();jobs=model.jobs()
  try:
   fixture.cfg.update(runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
   (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
   publicroot=fixture.job/'public-verification';shutil.copytree(fixture.job/'student',publicroot/'student');shutil.copytree(fixture.job/'tests',publicroot/'tests')
   def selection(folder,name):return {'projectRelativePath':folder+'/'+name,'submissionRelativePath':name,'sha256':hashlib.sha256((fixture.job/folder/name).read_bytes()).hexdigest()}
   src=selection('student','Student.java');test=selection('tests','AnswerTest.java');value=registry();rid=fixture.cfg['runtime']
   job=jobs.GradingJob(schemaVersion=1,scope='declared',qualifiedId='synthetic/exr-native',scenario='starter',sourceSnapshotHash='a'*64,inventoryHash='b'*64,runtime=rid,imageDigest=value['profiles'][rid]['image'],sources=[src],trustedTests=[test],verificationTests=[],grading=fixture.cfg,expectations={},sourceHashes={src['projectRelativePath']:src['sha256']},testsHashes={test['projectRelativePath']:test['sha256']});job.root=fixture.job
   selected=jobs._prepared_build_input_hash(job);prototype=model.observation()
   metadata=('schemaVersion','scope','backend','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes')
   primary={key:val for key,val in prototype.items() if key not in metadata};primary['buildEvidence']['inputHash']=selected
   failure={'classification':'infrastructure-failure','infrastructure':'failure','gradable':False,'grading_error':True,'message':'UNIT ONLY public build failure','buildEvidence':{'schemaVersion':1,'kind':'gradle-jar-v1','status':'failure','reason':'build','inputHash':selected,'dependencyHash':primary['buildEvidence']['dependencyHash']}}
   def container(command,**kwargs):
    mount=command[command.index('--mount')+1];path=Path(mount.split('src=',1)[1].split(',dst=',1)[0]);raw=failure if path==publicroot else primary
    (path/'results').mkdir();(path/'results/results.json').write_text(json.dumps(raw));return SimpleNamespace(returncode=2 if path==publicroot else 0,stdout='',stderr='')
   with patch.object(jobs.subprocess,'run',side_effect=container):result=jobs.run_job(job,'container',value)
   self.assertEqual(result['classification'],'infrastructure-failure');self.assertNotIn('score',result)
   self.assertEqual(result.get('studentCompilation'),'success');self.assertEqual(result.get('trustedCompilation'),'success')
   self.assertEqual(result['buildEvidence']['status'],'success');self.assertEqual(result['publicResult']['buildEvidence']['status'],'failure')
   self.assertEqual(jobs.verify_results([result],{},registry=value)['status'],'infrastructure-failure')
  finally:fixture.doCleanups()


class GradingRuntimeTransitionTests(unittest.TestCase):
 """Synthetic consumer checkpoint; actual JVM/DAC replay is separate evidence."""
 setUp=native.fixtures.JUnitJob.setUp
 def test_api_then_native_build_reopens_only_adapter_parent_before_junit(self):
  import os,stat,tempfile
  cfg=copy.deepcopy(self.cfg);cfg.update(runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'Main','artifact':'gradeapp.jar'},apiPrecheck={'files':['Api.java'],'entry':'Api'})
  cfg['testFiles'].append('Api.java');(self.job/'tests/Api.java').write_text('class Api {}')
  sources=grader._files(self.job/'student',cfg['sourceFiles']);tests=grader._files(self.job/'tests',cfg['testFiles']);phases=[]
  class ReachedJUnitCheckpoint(Exception):pass
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);bundle=root/'bundle';bundle.mkdir();(bundle/'fixture.jar').write_bytes(b'SYNTHETIC LIBRARY')
   home=root/'runtime';home.mkdir();runtime=grader._JobRuntime(home,bundle)
   runtime.compiler_archive.write_bytes(b'PRIVATE SYNTHETIC COMPILER ARCHIVE');runtime.compiler_archive.chmod(0o600)
   private=home/'additional-sources';private.mkdir(mode=0o700);(private/'Source.java').write_text('class Source {}');(private/'Source.java').chmod(0o600)
   def api(job,config,stage,*args):
    runtime.compiled=True;runtime.root.chmod(0o711);phases.append('api711');p=stage/'precheck';p.mkdir();return {'status':'success'},p,'synthetic-official'
   def build(stage,*args):
    stage.chmod(0o700);runtime.root.chmod(0o700);phases.append('build700');return {'status':'success'},lambda:None
   def child(command,*args,**kwargs):
    if 'PlatformJUnitAdapter' in command:
     self.assertEqual(stat.S_IMODE(runtime.root.stat().st_mode),0o711)
     self.assertEqual(stat.S_IMODE(private.stat().st_mode),0o700)
     self.assertEqual(stat.S_IMODE(runtime.compiler_archive.stat().st_mode),0o600)
     self.assertEqual(stat.S_IMODE((self.job/'tests').stat().st_mode),0o700)
     phases.append('junit711');raise ReachedJUnitCheckpoint()
    return 0,'',None
   real_is_file=Path.is_file
   def files(path):return True if str(path)=='/usr/local/bin/landlock_sandbox' else real_is_file(path)
   with patch.dict(os.environ,PL_CONTAINMENT='official'),patch.object(os,'geteuid',return_value=0),patch.object(Path,'is_file',files),patch.object(grader,'_protect_input_identity'),patch.object(grader,'_api_precheck',side_effect=api),patch.object(grader,'_run',side_effect=child):
    with self.assertRaises(ReachedJUnitCheckpoint):grader._execute(self.job,cfg,sources,tests,bundle,'synthetic JDK25',runtime,native_context={'build':build})
   self.assertEqual(phases,['api711','build700','junit711'])
