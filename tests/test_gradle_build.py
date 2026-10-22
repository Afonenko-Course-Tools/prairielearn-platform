"""Контракт Gradle: unit fixtures не являются доказательством image/toolchain."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_grading_job as fixtures

grader=fixtures.grader
ROOT=fixtures.ROOT

class MainApiExportTests(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 def run_job(self):
  from gradle_unit_fixtures import registry
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  return grader.grade(self.job,registry=registry())
 def test_trusted_selector_is_accessible_only_in_precheck_vm(self):
  self.cfg['testFiles'].append('ApiContract.java')
  self.cfg['apiPrecheck']={'files':['ApiContract.java'],'entry':'ApiContract'}
  (self.job/'tests/ApiContract.java').write_text('''import org.prairielearn.api.PlatformApiPrecheck;
public class ApiContract {public static void check(PlatformApiPrecheck.Api api) throws Exception {
 var finder=Class.forName("jdk.internal.misc.MethodFinder",false,null);
 api.expect(finder.getMethod("findMainMethod",Class.class).invoke(null,api.type("Student"))!=null,"launchable main","missing");
}}''')
  (self.job/'student/Student.java').write_text('public class Student {public static int answer(){return 42;} static void main(String[] args){}}')
  self.assertEqual(self.run_job()['classification'],'success')

class BuildContractTests(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 def native(self):
  return dict(self.cfg,runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
 def test_native_record_is_admitted_by_both_boundaries(self):
  import sys
  sys.path.insert(0,str(ROOT/'tools'));import grading_job as jobs
  config=self.native();grader.validate_config(config);jobs.validate('grading-descriptor',config)
  jobs.validate_profile({'runtime':'java25-gradle-junit-v1','sourceProfile':{'mode':'implementation','root':'src','include':['*.java']},'java-build':{'kind':'gradle-jar-v1','main-class':'grade.Main','artifact':'gradeapp.jar'}})
 def test_unsafe_or_wrong_runtime_build_record_is_rejected(self):
  import sys
  sys.path.insert(0,str(ROOT/'tools'));import grading_job as jobs
  for artifact in ['../gradeapp.jar','x/y.jar','.hidden.jar','a:b.jar','x*.jar','a\n.jar','a.jar.jar/'+('x'*130)]:
   config=self.native();config['javaBuild']['artifact']=artifact
   with self.subTest(artifact=artifact):
    with self.assertRaises(grader.GraderError):grader.validate_config(config)
    with self.assertRaises(jobs.JobError):jobs.validate('grading-descriptor',config)
  for runtime in ['java25-junit-v1','java25-mutation-v1','fish-git-v1']:
   config=self.native();config['runtime']=runtime
   with self.assertRaises(grader.GraderError):grader.validate_config(config)
  config=self.native();config.pop('javaBuild')
  with self.assertRaises(grader.GraderError):grader.validate_config(config)
 def test_successful_student_compile_does_not_permit_uncontained_gradle(self):
  from gradle_unit_fixtures import registry
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.native()))
  result=grader.grade(self.job,registry=registry())
  self.assertEqual(result['classification'],'infrastructure-failure')
  self.assertIn('containment',result['message']);self.assertFalse(result['gradable']);self.assertNotIn('score',result)
  self.assertEqual(result['buildEvidence']['status'],'failure')
 def test_original_selected_names_and_bytes_bind_input_hash(self):
  build=self.native()['javaBuild'];sources=[str(self.job/'student/Student.java')]
  first=grader._java_build_input(self.job,build,sources,{})
  canonical={'sources':{'Student.java':hashlib.sha256((self.job/'student/Student.java').read_bytes()).hexdigest()},'javaBuild':build}
  self.assertEqual(first,hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest())
  (self.job/'student/Student.java').write_text('class Student {}')
  self.assertNotEqual(first,grader._java_build_input(self.job,build,sources,{}))
 def test_artifact_guard_rejects_links_and_owner_write_drift(self):
  root=self.job/'build';root.mkdir(mode=0o755);libs=root/'libs';libs.mkdir(mode=0o755)
  artifact=libs/'gradeapp.jar';artifact.write_bytes(b'unit-only-jar-bytes');artifact.chmod(0o444)
  before=grader._artifact_state(self.job,'build/libs/gradeapp.jar',guarded=True)
  artifact.chmod(0o666)
  with self.assertRaises(grader.GraderError):grader._artifact_state(self.job,'build/libs/gradeapp.jar',guarded=True)
  artifact.chmod(0o444);artifact.unlink();artifact.symlink_to(self.job/'student/Student.java')
  with self.assertRaises(grader.GraderError):grader._artifact_state(self.job,'build/libs/gradeapp.jar',guarded=True)
  artifact.unlink();os.link(self.job/'student/Student.java',artifact)
  with self.assertRaises(grader.GraderError):grader._artifact_state(self.job,'build/libs/gradeapp.jar',guarded=False)
 def test_private_build_evidence_never_enters_student_feedback(self):
  import runpy
  result={'gradable':True,'score':1,'classification':'success','buildEvidence':{'artifact':{'path':'build/libs/gradeapp.jar'},'secret':'PRIVATE'},'diagnostics':{'gradleBuild':'PRIVATE'}}
  public=runpy.run_path(str(ROOT/'runtime/student_feedback.py'))['student_result'](result,self.cfg)
  self.assertNotIn('buildEvidence',public);self.assertNotIn('PRIVATE',json.dumps(public))

class BuildEvidenceTests(unittest.TestCase):
 def jobs(self):
  import sys
  sys.path.insert(0,str(ROOT/'tools'));import grading_job
  return grading_job
 def observation(self):
  import test_review_receipts as review
  from gradle_unit_fixtures import registry
  jobs=self.jobs()
  with patch.object(review.g,'load_runtime_registry',registry):r=review.result()
  r['runtime']='java25-gradle-junit-v1';r['imageDigest']=registry()['profiles'][r['runtime']]['image']
  r['executionEvidence']=jobs.runtime_evidence(r['runtime'],registry())
  r['buildEvidence']={'schemaVersion':1,'kind':'gradle-jar-v1','status':'success','inputHash':'2'*64,'dependencyHash':r['executionEvidence']['dependencyHash'],'artifact':{'path':'build/libs/gradeapp.jar','sha256':'3'*64,'bytes':42}}
  return r
 def test_missing_forged_or_wrong_stage_evidence_is_rejected(self):
  from gradle_unit_fixtures import registry
  jobs=self.jobs();r=self.observation();r.pop('buildEvidence')
  with self.assertRaises(jobs.JobError):jobs.verify_results([r],{},registry=registry())
  r=self.observation();r['buildEvidence']['dependencyHash']='4'*64
  with self.assertRaises(jobs.JobError):jobs.verify_results([r],{},registry=registry())
  r=self.observation();r['buildEvidence']={'schemaVersion':1,'kind':'gradle-jar-v1','status':'not-run'}
  with self.assertRaises(jobs.JobError):jobs.verify_results([r],{},registry=registry())
 def test_complete_receipt_requires_exact_native_scenario_evidence(self):
  import copy
  from gradle_unit_fixtures import registry
  jobs=self.jobs();r=self.observation();required=[{'qualifiedId':r['qualifiedId'],'scenario':r['scenario'],'optional':False}]
  receipt=jobs.verify_results([r],{},required,registry=registry())
  self.assertEqual(receipt['buildEvidence'],[{'qualifiedId':r['qualifiedId'],'scenario':r['scenario'],**r['buildEvidence'],'outcome':{key:r[key] for key in ('classification','infrastructure','studentCompilation','trustedCompilation','apiPrecheck','dependentExecution') if key in r}}])
  for mutate in ['missing','duplicate','extra','dependency']:
   bad=copy.deepcopy(receipt)
   if mutate=='missing':bad.pop('buildEvidence')
   elif mutate=='duplicate':bad['buildEvidence']*=2
   elif mutate=='extra':bad['buildEvidence'][0]['scenario']='contract:undeclared'
   else:bad['buildEvidence'][0]['dependencyHash']='5'*64
   bad['identityHash']=jobs.digest({k:v for k,v in bad.items() if k!='identityHash'})
   with self.subTest(mutate=mutate):
    with self.assertRaises(jobs.JobError):jobs.validate_receipt_integrity(bad)
 def test_compile_and_api_negatives_have_no_build_or_behavior(self):
  from gradle_unit_fixtures import registry
  fixture=fixtures.JUnitJob();fixture.setUp()
  try:
   fixture.cfg.update(runtime='java25-gradle-junit-v1',javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
   (fixture.job/'student/Student.java').write_text('not Java')
   (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
   r=grader.grade(fixture.job,registry=registry());self.assertEqual(r['classification'],'student-compilation-failure');self.assertEqual(r['buildEvidence']['status'],'not-run');self.assertNotIn('gradleBuild',r['durations'])
   fixture.cfg['testFiles'].append('ApiContract.java');fixture.cfg['apiPrecheck']={'files':['ApiContract.java'],'entry':'ApiContract'}
   (fixture.job/'student/Student.java').write_text('public class Student {}')
   (fixture.job/'tests/ApiContract.java').write_text('import org.prairielearn.api.PlatformApiPrecheck; public class ApiContract {public static void check(PlatformApiPrecheck.Api api)throws Exception {api.method("Student","answer",int.class,9,0);}}')
   (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
   r=grader.grade(fixture.job,registry=registry());self.assertEqual(r['classification'],'student-api-mismatch');self.assertEqual(r['buildEvidence']['status'],'not-run');self.assertEqual(r['dependentExecution'],'not-run');self.assertNotIn('gradleBuild',r['durations'])
  finally:fixture.doCleanups()

class PreparedNativeTests(unittest.TestCase):
 def test_prepare_preserves_record_and_binds_actual_reference_bytes(self):
  import sys,shutil
  sys.path.insert(0,str(ROOT/'tools'));import grading_job as jobs
  from gradle_unit_fixtures import registry
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);project=root/'tasks/p';project.mkdir(parents=True)
   content={'student/Student.java':'class Student {}','reference/Student.java':'class Student {int x=42;}','tests/T.java':'class T {}'}
   for name,text in content.items():
    p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
   def selected(name,out):return {'projectRelativePath':name,'submissionRelativePath':out,'sha256':hashlib.sha256((project/name).read_bytes()).hexdigest()}
   check={'runtime':'java25-gradle-junit-v1','sourceProfile':{'mode':'implementation','root':'student','include':['*.java']},'java-build':{'kind':'gradle-jar-v1','main-class':'grade.Main','artifact':'gradeapp.jar'},'references':[{'name':'default','root':'reference'}]}
   p={'qualifiedId':'synthetic/exr-native','projectRoot':'p','check':check,'sources':[selected('student/Student.java','Student.java')],'trustedTests':[selected('tests/T.java','T.java')],'references':[{'name':'default','sources':[selected('reference/Student.java','Student.java')]}]}
   manifest={'schemaVersion':1,'bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[p]}
   hashes=[]
   for scenario in ['starter','reference:default']:
    job=jobs.prepare_job(manifest,root,p['qualifiedId'],scenario,registry=registry())
    try:
     self.assertEqual(job['grading']['javaBuild'],{'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
     actual=jobs._prepared_build_input_hash(job);hashes.append(actual)
     expected=jobs.digest({'sources':{'Student.java':hashlib.sha256((job.root/'student/Student.java').read_bytes()).hexdigest()},'javaBuild':job['grading']['javaBuild']})
     self.assertEqual(actual,expected)
     original=(job.root/'student/Student.java').read_bytes()
     (job.root/'student/Student.java').write_text('class SubstitutedBeforeRun {}')
     with self.assertRaises(jobs.JobError):jobs._prepared_build_input_hash(job)
     (job.root/'student/Student.java').write_bytes(original)
     proof={'schemaVersion':1,'kind':'gradle-jar-v1','status':'success','inputHash':actual,'dependencyHash':'2'*64,'artifact':{'path':'build/libs/gradeapp.jar','sha256':'3'*64,'bytes':1}}
     result={'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','classification':'success','buildEvidence':proof}
     jobs._validate_build_observation(result,'2'*64,actual,'gradeapp.jar')
     proof['inputHash']='4'*64
     with self.assertRaises(jobs.JobError):jobs._validate_build_observation(result,'2'*64,actual,'gradeapp.jar')
    finally:shutil.rmtree(job.root)
   self.assertNotEqual(*hashes)

class NativeArtifactUnitTests(unittest.TestCase):
 """Эмуляция процесса Gradle проверяет guards; это НЕ actual Gradle/image proof."""
 setUp=fixtures.JUnitJob.setUp
 def build(self,mutation=None):
  from types import SimpleNamespace
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  stage=self.job/'private-stage';stage.mkdir();runtime_root=self.job/'private-runtime';runtime_root.mkdir()
  config=dict(self.cfg,javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'})
  lock={'jdk':{'home':'/unit-only-jdk'},'gradle':{'home':'/unit-only-gradle'}}
  def process(command,cwd,*args,**kwargs):
   if '--version' in command:return 0,'Gradle 9.8.0\n',None
   # The exact fixed offline argv is required at the process boundary.
   self.assertEqual(command,['/unit-only-gradle/bin/gradle','--offline','--no-daemon','--no-build-cache','--console=plain','--project-cache-dir',str(cwd/'project-cache'),'clean','jar'])
   self.assertNotIn('CLASSPATH',kwargs['env']);self.assertNotIn('JAVA_TOOL_OPTIONS',kwargs['env'])
   libs=cwd/'build/libs';libs.mkdir(parents=True)
   (libs/'gradeapp.jar').write_bytes(b'UNIT ONLY synthetic jar, never executable proof')
   if mutation:mutation(cwd)
   return 0,'UNIT ONLY process double\n',None
  with patch.object(grader,'_native_containment',return_value=(os.geteuid(),[])),patch.object(grader,'_verify_native_toolchain',return_value=lock),patch.object(grader,'_run',side_effect=process):
   return grader._native_build(self.job,config,[str(self.job/'student/Student.java')],{},stage,SimpleNamespace(root=runtime_root),'6'*64,{},{}),lock
 def test_fresh_artifact_is_guarded_and_post_execution_drift_is_rejected(self):
  (proof,verify),lock=self.build()
  self.assertEqual(proof['status'],'success');self.assertEqual(proof['artifact']['path'],'build/libs/gradeapp.jar')
  self.assertEqual((self.job/'build/libs/gradeapp.jar').stat().st_mode&0o777,0o444)
  private=self.job/'.native-build-private';self.assertEqual(private.stat().st_mode&0o777,0o700)
  with patch.object(grader,'_verify_native_toolchain',return_value=lock):verify()
  artifact=self.job/'build/libs/gradeapp.jar';artifact.chmod(0o644);artifact.write_bytes(b'UNIT ONLY retarget')
  with patch.object(grader,'_verify_native_toolchain',return_value=lock):
   with self.assertRaises(grader.GraderError):verify()
 def test_source_or_recipe_drift_never_hands_off_artifact(self):
  for kind in ['source','recipe','symlink','hardlink']:
   with self.subTest(kind=kind):
    # Each attempt gets its own job and scratch; never reuse an artifact.
    self.tmp.cleanup();fixtures.JUnitJob.setUp(self)
    def mutation(cwd):
     if kind=='source':(self.job/'student/Student.java').write_text('class Retarget {}')
     elif kind=='recipe':(cwd/'build.gradle').chmod(0o644);(cwd/'build.gradle').write_text('UNIT ONLY tamper')
     elif kind=='symlink':(cwd/'build/libs/gradeapp.jar').unlink();(cwd/'build/libs/gradeapp.jar').symlink_to(self.job/'student/Student.java')
     else:os.link(cwd/'build/libs/gradeapp.jar',cwd/'extra-link')
    with self.assertRaises(grader.GraderError):self.build(mutation)
    self.assertFalse((self.job/'build').exists())
 def test_preexisting_artifact_parent_refuses_before_build_child(self):
  from types import SimpleNamespace
  (self.job/'build').mkdir();stage=self.job/'stage';stage.mkdir()
  with patch.object(grader,'_native_containment',side_effect=AssertionError('build child must not run')):
   with self.assertRaises(grader.GraderError):
    grader._native_build(self.job,dict(self.cfg,javaBuild={'kind':'gradle-jar-v1','mainClass':'grade.Main','artifact':'gradeapp.jar'}),[],{},stage,SimpleNamespace(root=stage),'6'*64,{}, {})

class LegacyJavaControlTests(fixtures.JUnitJob):
 run_job=MainApiExportTests.run_job

class LegacyMutationControlTests(fixtures.MutationJob):
 run_job=MainApiExportTests.run_job

class PrivateLogRetentionTests(unittest.TestCase):
 def test_operator_evidence_survives_job_cleanup_in_private_output(self):
  import sys,shutil
  sys.path.insert(0,str(ROOT/'tools'));import grading_job as jobs
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);job=jobs.GradingJob(qualifiedId='synthetic/exr-native',scenario='starter',runtime='java25-gradle-junit-v1');job.root=root/'job';job.root.mkdir()
   private=job.root/'.native-build-private';private.mkdir(mode=0o700);(private/'gradle.log').write_text('UNIT ONLY private log');(private/'manifest.json').write_text('{}')
   destination=jobs.preserve_build_logs(job,root/'report.json');shutil.rmtree(job.root)
   self.assertEqual((destination/'gradle.log').read_text(),'UNIT ONLY private log')
   self.assertEqual(destination.stat().st_mode&0o777,0o700)
   manifest=json.loads((destination/'files.json').read_text());self.assertEqual(manifest['files']['gradle.log'],hashlib.sha256(b'UNIT ONLY private log').hexdigest())

class NativeClosureTests(unittest.TestCase):
 def test_explicit_registry_cannot_bypass_runner_or_recipe_hashes(self):
  from gradle_unit_fixtures import registry
  for component in ['runner','recipe']:
   value=registry();native=value['profiles']['java25-gradle-junit-v1']
   if component=='runner':native['runnerSha256']='0'*64
   else:native['sharedFiles']['runtime/gradle-jar-v1/build.gradle']='0'*64
   with self.subTest(component=component):
    with self.assertRaises(grader.GraderError):grader.preflight('java25-gradle-junit-v1',value)
 def test_historical_default_and_unadmitted_toolchain_refuse_execution(self):
  with self.assertRaisesRegex(grader.GraderError,'runner checksum'):grader.preflight('java25-junit-v1')
  with self.assertRaisesRegex(grader.GraderError,'admission is incomplete'):grader._verify_native_toolchain()

class NativeContainmentExecutableTests(unittest.TestCase):
 def test_resolved_supervisor_executable_survives_minimal_child_path(self):
  """Real process lookup only; mocked container facts are not sandbox proof."""
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);job=root/'job';job.mkdir()
   for name in ('student','tests'):(job/name).mkdir()
   selected=root/'sbin/runuser-selected';selected.parent.mkdir()
   selected.write_text('#!/usr/bin/python3\nprint(1001)\n');selected.chmod(0o755)
   real_run=grader._run;real_iterdir=Path.iterdir
   def launch(command,cwd,*args,**kwargs):
    self.assertEqual(kwargs['env']['PATH'],'/usr/bin:/bin')
    self.assertEqual(command[0],str(selected),'Use the admitted absolute executable, not a second PATH lookup')
    return real_run(command,cwd,*args,**kwargs)
   def directories(path):
    return iter([Path('/sys/class/net/lo')]) if path==Path('/sys/class/net') else real_iterdir(path)
   with patch.dict(os.environ,PL_CONTAINMENT='official'),patch.object(os,'geteuid',return_value=0),patch.object(Path,'is_file',return_value=True),patch.object(Path,'iterdir',directories),patch.object(grader.shutil,'which',return_value=str(selected)),patch.object(grader,'_protect_input_identity'),patch.object(grader,'_verify_landlock_helper'),patch.object(grader,'_role_records',return_value={'nativebuild':{'uid':1001,'gid':1001,'groups':[1001]},'sbuser':{'uid':1002,'gid':1002,'groups':[1002]}}),patch.object(grader,'_run',side_effect=launch):
    uid,prefix=grader._native_containment(job,[])
   self.assertEqual(uid,1001);self.assertEqual(prefix[0],str(selected));self.assertEqual(prefix[3],'nativebuild')


class SeparateNativeRolesTests(unittest.TestCase):
 """Synthetic role records/env; actual kernel gates remain separate."""
 def setUp(self):
  self.assertTrue(callable(getattr(grader,'_validate_role_records',None)),'Missing two-role isolation guard')
  self.roles={'sbuser':{'uid':1101,'gid':1101,'groups':[1101]},'nativebuild':{'uid':1102,'gid':1102,'groups':[1102]}}
 def test_distinct_private_groups_pass_and_collisions_or_extra_groups_refuse(self):
  import copy
  grader._validate_role_records(self.roles,{1000},{1000})
  for mutation in ['root','same-uid','same-gid','extra-group','build-group','mounted-uid','mounted-gid']:
   r=copy.deepcopy(self.roles)
   if mutation=='root':r['nativebuild']['uid']=0
   elif mutation=='same-uid':r['nativebuild']['uid']=1101
   elif mutation=='same-gid':r['nativebuild']['gid']=1101;r['nativebuild']['groups']=[1101]
   elif mutation=='extra-group':r['sbuser']['groups'].append(27)
   elif mutation=='build-group':r['sbuser']['groups'].append(1102)
   elif mutation=='mounted-uid':r['nativebuild']['uid']=1000
   else:r['nativebuild']['gid']=1000;r['nativebuild']['groups']=[1000]
   with self.subTest(mutation=mutation):
    with self.assertRaises(grader.GraderError):grader._validate_role_records(r,{1000},{1000})
  with self.assertRaises(grader.GraderError):grader._validate_role_records({'sbuser':self.roles['sbuser']},set(),set())
 def test_grade_environment_discards_inherited_native_and_jvm_options(self):
  with patch.dict(os.environ,{'PL_CONTAINMENT':'official','JAVA_HOME':'/opt/native-jdk','PATH':'/hostile','LD_PRELOAD':'/evil','JAVA_TOOL_OPTIONS':'-javaagent:/evil','_JAVA_OPTIONS':'-Dsecret=x','JDK_JAVA_OPTIONS':'-javaagent:/evil','JDK_JAVAC_OPTIONS':'-processor Evil','CLASSPATH':'/evil','HOME':'/tmp/build-home','GRADLE_USER_HOME':'/tmp/build-cache'}):
   env=grader._grading_environment()
  self.assertEqual(env,{'PATH':'/usr/lib/jvm/java-25-openjdk-amd64/bin:/usr/bin:/bin','JAVA_HOME':'/usr/lib/jvm/java-25-openjdk-amd64','HOME':'/nonexistent','TMPDIR':'/tmp','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'})
 def test_private_build_root_rejects_world_search_group_or_identity_drift(self):
  good={'uid':0,'gid':1102,'mode':0o750,'directory':True}
  grader._validate_build_root_record(good,1102)
  for key,value in [('mode',0o755),('mode',0o770),('gid',1101),('uid',1102),('directory',False)]:
   with self.subTest(key=key,value=value):
    with self.assertRaises(grader.GraderError):grader._validate_build_root_record(dict(good,**{key:value}),1102)
 def test_process_membership_uses_actual_uid_not_process_name(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary)
   for pid,uid in [(71,1102),(72,1101)]:
    p=root/str(pid);p.mkdir();(p/'status').write_text(f'Name: java\nUid: {uid} {uid} {uid} {uid}\nState: S (sleeping)\n');(p/'stat').write_text(str(pid)+' (java) S '+ ' '.join(['0']*18+['314159']+['0']*5))
   self.assertEqual(grader._build_process_records(root,1102),{71:{'uid':1102,'starttime':'314159','state':'S'}})


class HardenedCoreSelectionTests(unittest.TestCase):
 """Actual fixture bytes/FDs; only root ownership/outer parents are synthetic."""
 def test_changed_core_hash_missing_tool_or_restored_management_refuses(self):
  from types import SimpleNamespace
  import stat
  with tempfile.TemporaryDirectory() as temporary:
   home=Path(temporary)/'jdk';home.mkdir();files={}
   for name in ['release','bin/java','bin/javac','lib/modules','lib/server/libjvm.so']:
    p=home/name;p.parent.mkdir(parents=True,exist_ok=True);data=('UNIT '+name).encode();p.write_bytes(data);p.chmod(0o755 if name.startswith('bin/') else 0o644);files[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':oct(stat.S_IMODE(p.stat().st_mode))}
   lock=home.parent/'lock.json';lock.write_text(json.dumps({'jdk':{'files':files}}));real_lstat=Path.lstat;real_fstat=os.fstat
   def synthetic_root(s,outer=False):
    d={n:getattr(s,n) for n in dir(s) if n.startswith('st_')};d['st_uid']=0
    if outer:d['st_mode']=stat.S_IFDIR|0o755
    return SimpleNamespace(**d)
   def observed(path):return synthetic_root(real_lstat(path),path not in [home,*home.rglob('*')])
   with patch.object(grader,'HARDENED_JDK',home),patch.object(grader,'_files_any',return_value=lock),patch.object(Path,'lstat',observed),patch.object(os,'fstat',side_effect=lambda fd:synthetic_root(real_fstat(fd))):
    self.assertEqual(set(grader._hardened_tool_state()),set(files))
    library=home/'lib/modules';original=library.read_bytes();library.write_bytes(b'changed')
    with self.assertRaises(grader.GraderError):grader._hardened_tool_state()
    library.write_bytes(original);tool=home/'bin/javac';tool.unlink()
    with self.assertRaises((grader.GraderError,OSError)):grader._hardened_tool_state()
    tool.write_bytes(b'UNIT bin/javac');tool.chmod(0o755)
    (home/'lib/libmanagement.so').write_bytes(b'forbidden restored JNI')
    with self.assertRaises(grader.GraderError):grader._hardened_tool_state()


class NamespaceBoundaryTests(unittest.TestCase):
 def test_host_scope_cannot_reach_role_or_process_inventory(self):
  with patch.object(Path,'is_file',return_value=False),patch.object(os,'geteuid',return_value=0),patch.object(grader,'_role_records',side_effect=AssertionError('Unscoped role/process access')):
   with self.assertRaises(grader.GraderError):grader._grading_boundary()


class BuildTransitionCleanupTests(unittest.TestCase):
 def test_cleanup_binds_pid_identity_and_records_empty_remaining_set(self):
  first={71:{'uid':1102,'starttime':'15','state':'S'}}
  changed={71:{'uid':1102,'starttime':'16','state':'S'}}
  for rescan,expected in [(first,[71]),(changed,[])]:
   killed=[]
   with patch.object(Path,'is_file',return_value=True),patch.object(os,'geteuid',return_value=0),patch.object(grader,'_build_process_records',side_effect=[first,rescan,{}]),patch.object(os,'kill',side_effect=lambda pid,sig:killed.append(pid)),patch.object(os,'waitpid',side_effect=ChildProcessError):
    receipt=grader._finish_build_role(1102)
   self.assertEqual(killed,expected)
   self.assertEqual(receipt,{'uid':1102,'remaining':[],'terminated':expected,'reaped':[]})
