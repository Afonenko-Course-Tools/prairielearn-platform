"""Release assembly UNIT: exact local Git and files, no OCI/published release claim."""
from pathlib import Path
import json,os,tempfile,unittest,subprocess,sys
from unittest.mock import patch
from release_assembly_fixtures import AssemblyFixture,load,ROOT,git,write_json
sys.path.insert(0,str(ROOT/'tools'))
class ReleaseAssembly(unittest.TestCase):
 def test_exact_two_overlay_build_records_dirty_v2_and_actual_external_images(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);builder=load('assembly_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform;output=Path(name)/'native'
   with patch.dict(os.environ,{'PATH':str(f.binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}):builder.build_course(f.course,'tasks','pilot',output,runtime_registry=f.assets/'published-runtime-profiles.json')
   p=json.loads((output/'provenance.json').read_bytes());self.assertEqual(p['schema'],'pl-provenance-v2');self.assertIs(p['builder']['dirty'],True);self.assertEqual(p['builder']['mode'],'release-assembly');self.assertEqual(p['builder']['commit'],f.commit);self.assertEqual(p['platformImages'],f.images)
   self.assertEqual(set(p['builder']['releaseAssembly']['overlays']),{'runtime-profiles.json','runtime/gradle-jar-v1/toolchain-lock.json'})
   self.assertEqual(p['builder']['releaseAssembly']['overlays']['runtime/gradle-jar-v1/toolchain-lock.json']['sha256'],'c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca')

 def test_stage_cli_uses_external_images_and_accepts_current_v2_without_network(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);builder=load('stage_fixture_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform;output=Path(name)/'native'
   with patch.dict(os.environ,{'PATH':str(f.binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}):builder.build_course(f.course,'tasks','pilot',output,runtime_registry=f.assets/'published-runtime-profiles.json')
   repository='https://example.invalid/unit-native.git';git(output,'init','-q');git(output,'remote','add','origin',repository);git(output,'add','-A');git(output,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT qualified native')
   commit=git(output,'rev-parse','HEAD');storage=Path(name)/'storage';parent=storage/'unit-course';parent.mkdir(parents=True);destination=parent/commit;output.rename(destination)
   registry=Path(name)/'courses.json';write_json(registry,{'schema':'pl-courses-v1','courses':[{'id':'unit-course','repository':repository,'commit':commit,'mount':'/course'}]})
   override=Path(name)/'mounts.json';q=subprocess.run([sys.executable,'-B',str(f.platform/'tools/stage_courses.py'),str(registry),'--images',str(f.assets/'images.lock.json'),'--storage',str(storage),'--compose-output',str(override)],capture_output=True,timeout=30,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
   self.assertEqual(q.returncode,0,q.stderr.decode());self.assertEqual(json.loads(override.read_bytes())['services']['pl']['volumes'][0]['source'],str(destination));self.assertEqual(git(destination,'status','--porcelain'),'')

 def test_stage_registry_explicit_assembly_root_preserves_original_context(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);stage=load('separate_host_stage',ROOT/'tools/stage_courses.py')
   images=json.loads((f.assets/'images.lock.json').read_bytes())
   course={'id':'unit-course','repository':'https://example.invalid/unit-native.git','commit':'1'*40,'mount':'/course'}
   registry={'schema':'pl-courses-v1','courses':[course]};seen=[]
   def accept(record,storage,institutions,actual_images,assembly,admission_policy=None,admission_policy_sha256=None):
    assembly.recheck();self.assertEqual(assembly.builder['commit'],f.commit);self.assertEqual(actual_images,images);seen.append(assembly);return Path(name)/'native'
   with patch.object(stage,'stage_course',accept):
    result=stage.stage_registry(registry,images,Path(name),images_path=f.assets/'images.lock.json',assembly_root=f.platform)
   self.assertEqual(len(seen),1);self.assertEqual(result['services']['pl']['volumes'][0]['source'],str(Path(name)/'native'))
   stage.builder.PLATFORM=f.platform
   with patch.object(stage,'stage_course',accept):stage.stage_registry(registry,images,Path(name),images_path=f.assets/'images.lock.json')
   for bad in [Path(name)/'missing',Path('relative')]:
    with self.subTest(root=bad),self.assertRaises(stage.StorageError):stage.stage_registry(registry,images,Path(name),images_path=f.assets/'images.lock.json',assembly_root=bad)
   link=Path(name)/'alias';link.symlink_to(f.platform,target_is_directory=True)
   with self.assertRaises(stage.StorageError):stage.stage_registry(registry,images,Path(name),images_path=f.assets/'images.lock.json',assembly_root=link)
   original=(f.assets/'runtime-image.json').read_bytes();(f.assets/'runtime-image.json').write_bytes(original+b' ')
   with self.assertRaises(stage.StorageError):stage.stage_registry(registry,images,Path(name),images_path=f.assets/'images.lock.json',assembly_root=f.platform)
 def context(self,f):
  return load('unit_closed_assembly',ROOT/'tools/release_assembly.py').Context(f.platform,f.assets/'images.lock.json')

 def test_external_assets_and_source_identity_are_closed(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);original=(f.assets/'images.lock.json').read_bytes()
   mutations=[('missing-descriptor',lambda v:v.pop('releaseAssembly')),('unknown-descriptor-field',lambda v:v['releaseAssembly'].update(extra=True)),('wrong-commit',lambda v:v['releaseAssembly'].update(sourceCommit='0'*40)),('wrong-tree',lambda v:v['releaseAssembly'].update(sourceTree='0'*40)),('wrong-version',lambda v:v['releaseAssembly'].update(version='2.3.1',tag='v2.3.1')),('wrong-tag',lambda v:v['releaseAssembly'].update(tag='v2.3.1')),('wrong-java-image',lambda v:v['javaGrader'].update(image='ghcr.io/unit-example/java25-grader@sha256:'+'8'*64)),('upstream-source',lambda v:v['prairielearn'].update(sourceCommit='0'*40)),('extra-asset-pin',lambda v:v['releaseAssembly']['assets'].update(extra='a'*64))]
   for label,mutate in mutations:
    with self.subTest(label=label):
     v=json.loads(original);mutate(v);write_json(f.assets/'images.lock.json',v,0o600)
     with self.assertRaises((ValueError,subprocess.SubprocessError)):self.context(f)
   (f.assets/'images.lock.json').write_bytes(original)
   asset=f.assets/'runtime-image.json';saved=asset.read_bytes();asset.unlink()
   with self.assertRaisesRegex(ValueError,'asset directory inventory'):self.context(f)
   asset.write_bytes(saved);asset.chmod(0o644)
   with self.assertRaises(ValueError):self.context(f)
   asset.chmod(0o600);self.context(f)

 def test_self_consistent_forged_registry_and_old_lock_are_not_authority(self):
  import hashlib
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);raw={p.name:p.read_bytes() for p in f.assets.iterdir()};reg=json.loads(raw['published-runtime-profiles.json'])
   def trial(label,registry=None,lock=None):
    for n,b in raw.items():(f.assets/n).write_bytes(b)
    if registry is not None:write_json(f.assets/'published-runtime-profiles.json',registry,0o600)
    if lock is not None:(f.assets/'published-toolchain-lock.json').write_bytes(lock)
    receipt=json.loads(raw['runtime-image.json']);receipt['runtimeProfilesSha256']=hashlib.sha256((f.assets/'published-runtime-profiles.json').read_bytes()).hexdigest();write_json(f.assets/'runtime-image.json',receipt,0o600)
    images=json.loads(raw['images.lock.json']);images['releaseAssembly']['assets']={n:hashlib.sha256((f.assets/n).read_bytes()).hexdigest() for n in images['releaseAssembly']['assets']};write_json(f.assets/'images.lock.json',images,0o600)
    (f.platform/'runtime-profiles.json').write_bytes((f.assets/'published-runtime-profiles.json').read_bytes());(f.platform/'runtime/gradle-jar-v1/toolchain-lock.json').write_bytes((f.assets/'published-toolchain-lock.json').read_bytes())
    with self.subTest(label=label),self.assertRaisesRegex(ValueError,'source-derived registry/generated lock'):self.context(f)
   import copy
   for label,profile,field in [('runner','java25-junit-v1','runner'),('config','java25-junit-v1','configFiles'),('dependency','java25-junit-v1','dependencies'),('fish','fish-git-v1','runner')]:
    v=copy.deepcopy(reg);v['profiles'][profile][field]={'forged':'a'*64};trial(label,registry=v)
   trial('old-source-lock',lock=subprocess.check_output(['git','show','HEAD:runtime/gradle-jar-v1/toolchain-lock.json'],cwd=f.platform))

 def test_source_physical_index_modes_and_extra_files_remain_strict(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);self.context(f);target=f.platform/'tools/build-course.py';original=target.read_bytes()
   changes=[('third-code-file',lambda:target.write_bytes(original+b'\n'),lambda:target.write_bytes(original)),('mode',lambda:target.chmod(0o600),lambda:target.chmod(0o644)),('ignored-cache',lambda:(f.platform/'__pycache__').mkdir(),lambda:(f.platform/'__pycache__').rmdir()),('extra',lambda:(f.platform/'EXTRA').write_text('not allowed'),lambda:(f.platform/'EXTRA').unlink()),('symlink',lambda:(f.platform/'link').symlink_to(target),lambda:(f.platform/'link').unlink()),('staged-overlay',lambda:git(f.platform,'add','runtime-profiles.json'),lambda:git(f.platform,'restore','--staged','runtime-profiles.json')),('skip-worktree',lambda:git(f.platform,'update-index','--skip-worktree','tools/build-course.py'),lambda:git(f.platform,'update-index','--no-skip-worktree','tools/build-course.py'))]
   for label,change,restore in changes:
    with self.subTest(label=label):
     change()
     try:
      with self.assertRaises(ValueError):self.context(f)
     finally:restore()
   self.context(f)

 def test_no_legacy_downgrade_and_candidate_image_in_release_build(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);builder=load('no_downgrade_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform
   for registry,candidate in [(f.platform/'runtime-profiles.json',None),(f.assets/'published-runtime-profiles.json','unit:local')]:
    with self.subTest(registry=str(registry),candidate=candidate),self.assertRaises(builder.BuildError):builder.build_course(f.course,'tasks','pilot',Path(name)/'not-published',registry,candidate)
    self.assertFalse((Path(name)/'not-published').exists())
   assembly=load('no_downgrade_reader',ROOT/'tools/release_assembly.py')
   with self.assertRaises(ValueError):assembly.for_stage(f.platform,json.loads(subprocess.check_output(['git','show','HEAD:images.lock.json'],cwd=f.platform)))

 def test_mid_export_assets_or_code_mutation_never_publish_output(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);builder=load('mid_export_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform
   for i,target in enumerate([f.assets/'runtime-image.json',f.platform/'tools/stage_courses.py']):
    saved=target.read_bytes();out=Path(name)/('native-'+str(i))
    try:
     with patch.dict(os.environ,{'PATH':str(f.binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1','UNIT_ASSEMBLY_MUTATION':str(target)}),self.assertRaisesRegex(builder.BuildError,'changed during export'):builder.build_course(f.course,'tasks','pilot',out,f.assets/'published-runtime-profiles.json')
     self.assertFalse(out.exists());self.assertFalse(out.with_name(out.name+'-checks.json').exists())
    finally:target.write_bytes(saved)

 def build_and_pin(self,f,root,source=None,receipt=None):
  builder=load('qualified_unit_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform;out=root/'native'
  with patch.dict(os.environ,{'PATH':str(f.binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}):builder.build_course(source or f.course,'tasks','pilot',out,runtime_registry=f.assets/'published-runtime-profiles.json',staging_receipt=receipt)
  git(out,'init','-q');git(out,'remote','add','origin','https://example.invalid/unit-native.git');git(out,'add','-A');git(out,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT native qualification')
  return out,{'id':'unit-course','repository':'https://example.invalid/unit-native.git','commit':git(out,'rev-parse','HEAD'),'mount':'/course'}

 def test_native_forgery_missing_qualification_and_without_external_context_refused(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);out,course=self.build_and_pin(f,root);stage=load('qualified_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json')
   stage.validate_checkout(out,course,context)
   with self.assertRaises(stage.StorageError):stage.validate_checkout(out,course)
   original=(out/'provenance.json').read_bytes()
   for label,change in [('dirty-false',lambda p:p['builder'].update(dirty=False)),('self-pinned-tree',lambda p:p['builder']['releaseAssembly'].update(sourceTree='a'*40)),('forged-images',lambda p:p['platformImages']['javaGrader'].update(image='unit:forged')),('unknown-v2-field',lambda p:p.update(extra=True)),('dirty-source',lambda p:p['source'].update(dirty=True)),('wrong-source-book',lambda p:p['source'].update(book='other'))]:
    p=json.loads(original);change(p);write_json(out/'provenance.json',p);git(out,'add','provenance.json');git(out,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm',label);course['commit']=git(out,'rev-parse','HEAD')
    with self.subTest(label=label),self.assertRaises(stage.StorageError):stage.validate_checkout(out,course,context)
   (out/'provenance.json').write_bytes(original);(out/'verification-receipt.json').unlink();git(out,'add','-A');git(out,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','missing qualification');course['commit']=git(out,'rev-parse','HEAD')
   with self.assertRaises(stage.StorageError):stage.validate_checkout(out,course,context)

 def test_private_stage_existing_shape_builds_and_stages_without_producer_path_read(self):
  import hashlib,shutil
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);core=root/'core';data=b'PRIVATE_UNIT_REFERENCE\n';target='projects/demo/reference/Main.java';(core/target).parent.mkdir(parents=True);(core/target).write_bytes(data)
   manifest={'schema':'course-project-materialization-v1','audience':'grading','sourceRoot':str(f.course/'tasks'),'sourceCommit':git(f.course,'rev-parse','HEAD'),'exerciseIds':['exr-manual'],'projects':[{'exerciseId':'exr-manual','projectRoot':'projects/demo'}],'replacementRoots':['projects/demo/'+p for p in ['student','reference','tests','rubric.md','contract.md']],'files':[{'source':str(root/'teacher/Main.java'),'target':target,'origin':'teacher','sha256':hashlib.sha256(data).hexdigest()}],'commonSources':{},'sourceDocuments':{'demo.qmd':hashlib.sha256((f.course/'tasks/demo.qmd').read_bytes()).hexdigest()},'declarationsHash':'a'*64}
   write_json(core/'materialization.json',manifest);private=load('assembly_private_prepare',ROOT/'tools/prepare-private-source.py');source=root/'private';receipt=root/'private-receipt.json';private.prepare(f.course,'tasks',core,source,receipt)
   out,course=self.build_and_pin(f,root,source,receipt);p=json.loads((out/'provenance.json').read_bytes());s=p['source'];self.assertEqual(s['mode'],'private-stage');self.assertNotIn('commit',s);self.assertNotEqual(s['publicBase']['commit'],s['privateStage']['commit']);self.assertEqual(s['runtimeInventory'],{});self.assertNotIn(data,b''.join(x.read_bytes() for x in out.rglob('*') if x.is_file() and '.git' not in x.parts))
   shutil.rmtree(source);receipt.unlink() # Server never follows producer's historical absolute path.
   stage=load('private_qualified_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');stage.validate_checkout(out,course,context)
   original=(out/'provenance.json').read_bytes()
   for field in ['publicBase','privateStage','stagingReceiptSha256','materialization','runtimeInventory']:
    p=json.loads(original);p['source'].pop(field);write_json(out/'provenance.json',p);git(out,'add','provenance.json');git(out,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','missing '+field);course['commit']=git(out,'rev-parse','HEAD')
    with self.subTest(missing=field),self.assertRaises(stage.StorageError):stage.validate_checkout(out,course,context)

 def test_assets_directory_has_no_unadmitted_sibling(self):
  with tempfile.TemporaryDirectory() as name:
   f=AssemblyFixture(name);(f.assets/'orphan.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'asset directory inventory'):self.context(f)

 def test_mid_stage_source_or_asset_change_refuses_atomic_destination(self):
  import shutil
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);native,course=self.build_and_pin(f,root);stage=load('mid_stage_reader',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform
   for i,target in enumerate([f.assets/'runtime-image.json',f.platform/'tools/stage_courses.py']):
    context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');storage=root/('storage-'+str(i));storage.mkdir();saved=target.read_bytes();original_validate=stage.validate_checkout;original_git=stage.git
    def local_git(directory,*args):
     if args[0]=='clone':shutil.copytree(native,Path(args[-1]));return ''
     return original_git(directory,*args)
    def after_validation(*args):
     original_validate(*args);target.write_bytes(saved+b'\n')
    try:
     with patch.object(stage,'git',local_git),patch.object(stage,'validate_checkout',after_validation),self.assertRaises(stage.StorageError):stage.stage_course(course,storage,images=context.images,assembly=context)
     self.assertFalse((storage/course['id']/course['commit']).exists())
    finally:target.write_bytes(saved)

 def test_native_payload_drift_during_final_assembly_recheck_refused(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);native,course=self.build_and_pin(f,root);stage=load('native_aftercheck_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');real_recheck=context.recheck;calls=0
   def during_recheck():
    nonlocal calls
    calls+=1;real_recheck()
    if calls==2:(native/'questions/demo/exr-manual/question.html').write_text('MID_STAGE_NATIVE_DRIFT')
   with patch.object(context,'recheck',during_recheck),self.assertRaises(stage.StorageError):stage.validate_checkout(native,course,context)

 def test_native_git_symlink_during_final_assembly_recheck_refused(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);native,course=self.build_and_pin(f,root);stage=load('native_git_aftercheck_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');real_recheck=context.recheck;calls=0
   def during_recheck():
    nonlocal calls
    calls+=1;real_recheck()
    if calls==2:
     target=root/'historical-native-git';(native/'.git').rename(target);(native/'.git').symlink_to(target,target_is_directory=True)
   with patch.object(context,'recheck',during_recheck),self.assertRaises(stage.StorageError):stage.validate_checkout(native,course,context)

 def test_native_special_mode_bits_do_not_match_git_regular_mode(self):
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);native,course=self.build_and_pin(f,root);stage=load('native_mode_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json')
   (native/'questions/demo/exr-manual/question.html').chmod(0o4644)
   with self.assertRaises(stage.StorageError):stage.validate_checkout(native,course,context)

 def test_native_root_symlink_during_final_recheck_refuses_atomic_publication(self):
  import shutil
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);native,course=self.build_and_pin(f,root);stage=load('native_root_aftercheck_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');real_recheck=context.recheck;real_git=stage.git;calls=0;pending=None
   storage=root/'storage';storage.mkdir();identical=root/'identical-native'
   def local_git(directory,*args):
    nonlocal pending
    if args[0]=='clone':
     pending=Path(args[-1]);shutil.copytree(native,pending);return ''
    return real_git(directory,*args)
   def during_recheck():
    nonlocal calls
    calls+=1;real_recheck()
    if calls==4:
     shutil.copytree(pending,identical);pending.rename(pending.with_name('original-native'));pending.symlink_to(identical,target_is_directory=True)
     self.assertEqual(git(pending,'rev-parse','HEAD'),course['commit']);self.assertEqual(git(pending,'status','--porcelain'),'')
   with patch.object(stage,'git',local_git),patch.object(context,'recheck',during_recheck),self.assertRaises(stage.StorageError):stage.stage_course(course,storage,images=context.images,assembly=context)
   self.assertEqual(calls,4);self.assertFalse((storage/course['id']/course['commit']).exists());self.assertFalse((storage/course['id']/course['commit']).is_symlink())

 def test_real_manual_qualification_is_attached_before_native_git_freeze(self):
  import hashlib
  with tempfile.TemporaryDirectory() as name:
   root=Path(name);f=AssemblyFixture(name);builder=load('qualification_order_builder',ROOT/'tools/build-course.py');builder.PLATFORM=f.platform;out=root/'native'
   # Only the fake export boundary is adjusted: actual owner manifests have v1,
   # and qualification is emitted later by the existing real check-course CLI.
   script=f.binary/'quarto';script.write_text(script.read_text().replace("c={'sourceSnapshotHash':","c={'schemaVersion':1,'bookRoot':'tasks','sourceSnapshotHash':")+"\n(out/'verification-receipt.json').unlink()\n")
   with patch.dict(os.environ,{'PATH':str(f.binary)+os.pathsep+os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}):builder.build_course(f.course,'tasks','pilot',out,runtime_registry=f.assets/'published-runtime-profiles.json')
   provenance=json.loads((out/'provenance.json').read_bytes());self.assertFalse((out/'verification-receipt.json').exists());self.assertNotIn('verification-receipt.json',provenance['files'])
   report_path=root/'qualification-report.json';command=[sys.executable,'-B',str(f.platform/'tools/check-course.py'),'verify','--manifest',str(root/'native-checks.json'),'--snapshot',str(f.course),'--scope','delivery','--delivery',str(out/'delivery.json'),'--output',str(report_path),'--runtime-registry',str(f.assets/'published-runtime-profiles.json')]
   actual=subprocess.run(command,capture_output=True,text=True,timeout=30,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'});self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
   report=json.loads(report_path.read_bytes());self.assertEqual(report['automatic']['state'],'not-applicable');self.assertEqual(report['results'],[])
   stage=load('qualification_order_stage',ROOT/'tools/stage_courses.py');stage.builder.PLATFORM=f.platform;delivery=json.loads((out/'delivery.json').read_bytes())
   with self.assertRaises(stage.JobError):stage.validate_release_receipt(report,delivery,out,f.registry)
   stage.validate_release_receipt(report['receipt'],delivery,out,f.registry)
   write_json(out/'verification-receipt.json',report['receipt']);provenance['files']['verification-receipt.json']=hashlib.sha256((out/'verification-receipt.json').read_bytes()).hexdigest();write_json(out/'provenance.json',provenance)
   git(out,'init','-q');git(out,'remote','add','origin','https://example.invalid/unit-native.git');git(out,'add','-A');git(out,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT qualified native after real check-course')
   course={'id':'unit-course','repository':'https://example.invalid/unit-native.git','commit':git(out,'rev-parse','HEAD'),'mount':'/course'};context=stage.builder._assembly.Context(f.platform,f.assets/'images.lock.json');stage.validate_checkout(out,course,context)
