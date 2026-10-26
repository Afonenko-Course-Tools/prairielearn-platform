"""Точный Core inventory становится чистым приватным snapshot без remote."""
from gradle_unit_fixtures import write_registry as unit_registry_file
import hashlib,importlib.util,json,os,subprocess,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
spec=importlib.util.spec_from_file_location('private_source',Path(__file__).resolve().parents[1]/'tools/prepare-private-source.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
def git(root,*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
class PrivateSource(unittest.TestCase):
 def test_snapshot_and_drift_guards(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);public=root/'public';public.mkdir();git(public,'init','-q');git(public,'remote','add','origin','https://example.invalid/course.git')
   write(public/'.gitignore','**/_generated/\n**/.quarto/\n.quarto/\nignored/\n')
   write(public/'tasks/_quarto.yml','project: {type: website}\n');write(public/'tasks/numbers.qmd','PUBLIC_CONDITION');write(public/'tasks/projects/demo/student/Main.java','PUBLIC_NEW');write(public/'tasks/projects/demo/README.md','KEEP_OWNER_FILE')
   write(public/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts','// fixture boundary')
   git(public,'add','.');git(public,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Public')
   write(public/'tasks/projects/demo/student/.git/HEAD','ref: refs/heads/main\n')
   core=root/'core';files=[]
   for name,data,origin in [('student/Main.java','PUBLIC_NEW','public'),('reference/Main.java','PRIVATE_CANARY','teacher'),('student/.git/HEAD','ref: refs/heads/main\n','public')]:
    target='projects/demo/'+name;write(core/target,data);files.append({'target':target,'source':str(public/'tasks'/target),'sha256':hashlib.sha256(data.encode()).hexdigest(),'origin':origin})
   manifest={'schema':'course-project-materialization-v1','audience':'grading','sourceRoot':str(public/'tasks'),'sourceCommit':git(public,'rev-parse','HEAD'),'exerciseIds':['exr-demo'],'projects':[{'exerciseId':'exr-demo','projectRoot':'projects/demo'}],'replacementRoots':['projects/demo/'+p for p in ['student','reference','tests','rubric.md','contract.md']],'files':files,'commonSources':{},'sourceDocuments':{'numbers.qmd':hashlib.sha256(b'PUBLIC_CONDITION').hexdigest()},'declarationsHash':'a'*64}
   write(core/'materialization.json',json.dumps(manifest));output=root/'private';receipt=root/'receipt.json'
   for index,bad_receipt in enumerate([public/'new-receipt.json',core/'new-receipt.json']):
    before_public=stage.inventory(public);before_core=stage.inventory(core);bad_output=root/('bad-output-'+str(index))
    with self.assertRaises(stage.StageError):stage.prepare(public,'tasks',core,bad_output,bad_receipt)
    self.assertEqual(stage.inventory(public),before_public);self.assertEqual(stage.inventory(core),before_core);self.assertFalse(bad_output.exists())
   stage.prepare(public,'tasks',core,output,receipt)
   self.assertEqual((output/'tasks/numbers.qmd').read_text(),'PUBLIC_CONDITION');self.assertEqual((output/'tasks/projects/demo/README.md').read_text(),'KEEP_OWNER_FILE');self.assertEqual((output/'tasks/projects/demo/reference/Main.java').read_text(),'PRIVATE_CANARY');self.assertEqual(git(output,'remote'),'');self.assertEqual(git(output,'status','--porcelain','--untracked-files=all'),'')
   identity=stage.validate(output,receipt);self.assertEqual(identity['publicBase']['commit'],git(public,'rev-parse','HEAD'));self.assertIn('tasks/projects/demo/student/.git/HEAD',identity['seedFiles'])
   builder_spec=importlib.util.spec_from_file_location('builder',Path(__file__).resolve().parents[1]/'tools/build-course.py');builder=importlib.util.module_from_spec(builder_spec);builder_spec.loader.exec_module(builder)
   binary=root/'bin';binary.mkdir();script=binary/'quarto'
   script.write_text("""#!/usr/bin/env python3
import json,pathlib,sys,os
out=pathlib.Path(sys.argv[4]);out.mkdir();checks=pathlib.Path(sys.argv[8])
(out/'infoCourse.json').write_text(json.dumps({'name':'SYN'}))
q=out/'questions/synthetic/exr-a';q.mkdir(parents=True)
(q/'info.json').write_text(json.dumps({'uuid':'00000000-0000-4000-8000-000000000001'}))
delivery={'schemaVersion':3,'deliveryHash':'c'*64,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'questions':['synthetic/exr-a']}
(out/'delivery.json').write_text(json.dumps(delivery));checks.write_text(json.dumps({'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64}))
if os.environ.get('ALTER_SEED'):pathlib.Path('tasks/projects/demo/student/.git/EXTRA').write_text('POST_EXPORT_DRIFT')
""");script.chmod(0o755)
   with patch.dict(os.environ,{'PATH':str(binary)+os.pathsep+os.environ['PATH']}):
    builder.build_course(output,'tasks','pilot',root/'candidate',staging_receipt=receipt,runtime_registry=unit_registry_file(root))
    provenance=json.loads((root/'candidate/provenance.json').read_text())['source']
    self.assertEqual(provenance['mode'],'private-stage');self.assertNotIn('commit',provenance);self.assertEqual(provenance['publicBase']['commit'],git(public,'rev-parse','HEAD'))
    with patch.dict(os.environ,{'ALTER_SEED':'1'}):
     with self.assertRaises(builder.BuildError):builder.build_course(output,'tasks','pilot',root/'bad-candidate',staging_receipt=receipt,runtime_registry=unit_registry_file(root))
    self.assertFalse((root/'bad-candidate').exists());self.assertFalse((root/'bad-candidate-checks.json').exists())
   (output/'tasks/projects/demo/student/.git/EXTRA').unlink()
   runtime=output/'tasks/_generated/result.json';write(runtime,'RUNTIME')
   stage.validate(output,receipt,allow_runtime=True)
   self.assertEqual(stage.runtime_inventory(output,identity),{'tasks/_generated/result.json':hashlib.sha256(b'RUNTIME').hexdigest()})
   with self.assertRaises(stage.StageError):stage.validate(output,receipt)
   (runtime.parent/'link').symlink_to(output/'tasks/numbers.qmd')
   with self.assertRaises(stage.StageError):stage.validate(output,receipt,allow_runtime=True)
   (runtime.parent/'link').unlink();runtime.unlink();runtime.parent.rmdir()
   write(output/'ignored/addition','UNAUTHORIZED_IGNORED')
   with self.assertRaises(stage.StageError):stage.validate(output,receipt,allow_runtime=True)
   (output/'ignored/addition').unlink();(output/'ignored').rmdir()
   original=output/'tasks/numbers.qmd';original.write_text('MUTATED_SOURCE')
   with self.assertRaises(stage.StageError):stage.validate(output,receipt,allow_runtime=True)
   original.write_text('PUBLIC_CONDITION')
   original_manifest=(core/'materialization.json').read_bytes();missing_commit=dict(manifest);missing_commit.pop('sourceCommit');(core/'materialization.json').write_text(json.dumps(missing_commit))
   with self.assertRaises(stage.StageError):stage.prepare(public,'tasks',core,root/'missing-commit-stage',root/'missing-commit-receipt.json')
   self.assertFalse((root/'missing-commit-stage').exists());(core/'materialization.json').write_bytes(original_manifest)
   config=public/'tasks/_quarto.yml';config.write_text(config.read_text()+'# CONFIG_ONLY_COMMIT\n');git(public,'add','tasks/_quarto.yml');git(public,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Config only')
   with self.assertRaises(stage.StageError):stage.prepare(public,'tasks',core,root/'config-drift-stage',root/'config-drift-receipt.json')
   self.assertFalse((root/'config-drift-stage').exists());self.assertFalse((root/'config-drift-receipt.json').exists())
   seed=output/'tasks/projects/demo/student/.git/HEAD';seed.write_text('DRIFT')
   with self.assertRaises(stage.StageError):stage.validate(output,receipt)
   seed.write_text('ref: refs/heads/main\n');write(seed.parent/'extra','ADDED')
   with self.assertRaises(stage.StageError):stage.validate(output,receipt)
 def test_unrelated_replacement_rejected_without_output(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);public=root/'public';public.mkdir();git(public,'init','-q');git(public,'remote','add','origin','https://example.invalid/course.git');write(public/'tasks/x','x');git(public,'add','.');git(public,'-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','F')
   core=root/'core';write(core/'materialization.json',json.dumps({'schema':'course-project-materialization-v1','audience':'grading','sourceRoot':str(public/'tasks'),'sourceCommit':git(public,'rev-parse','HEAD'),'projects':[{'exerciseId':'exr-demo','projectRoot':'projects/demo'}],'replacementRoots':['_quarto.yml'],'files':[]}))
   with self.assertRaises(stage.StageError):stage.prepare(public,'tasks',core,root/'out',root/'receipt.json')
   self.assertFalse((root/'out').exists())
   write(core/'materialization.json',json.dumps([{'name':'README.md','bytes':[1,2]}]))
   with self.assertRaisesRegex(stage.StageError,'artifact files'):stage.prepare(public,'tasks',core,root/'artifact-stage',root/'artifact-receipt.json')
   self.assertFalse((root/'artifact-stage').exists())

class GeneratedExecutionSource(unittest.TestCase):
 def fixture(self,root):
  public=root/'public';public.mkdir();git(public,'init','-q');git(public,'remote','add','origin','https://example.invalid/course.git')
  for name,data in {'.gitignore':'ignored/\n**/.quarto/\n**/_generated/\n','tasks/_quarto.yml':'project: {type: website}\n','tasks/lab.qmd':'PUBLIC','tasks/shared.txt':'COMMON','tasks/projects/demo/student/main.txt':'STARTER'}.items():write(public/name,data)
  git(public,'add','.');git(public,'-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','Public')
  execution=root/'execution';git(root,'clone','-q','--no-hardlinks',str(public),str(execution));git(execution,'remote','set-url','origin','https://example.invalid/course.git')
  write(execution/'tasks/projects/demo/student/seed/data.txt','INITIAL_ONLY');write(execution/'tasks/projects/demo/student/seed/.git/HEAD','ref: refs/heads/main\n')
  core=root/'core';files=[]
  for name in ['main.txt','seed/data.txt','seed/.git/HEAD']:
   target='projects/demo/student/'+name;source=execution/'tasks'/target;data=source.read_bytes();p=core/target;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);files.append({'target':target,'source':str(source),'sha256':hashlib.sha256(data).hexdigest(),'origin':'public'})
  data=b'COMMON';write(core/'projects/demo/tests/shared.txt',data.decode());files.append({'target':'projects/demo/tests/shared.txt','source':str(execution/'tasks/shared.txt'),'sha256':hashlib.sha256(data).hexdigest(),'origin':'common'})
  manifest={'schema':'course-project-materialization-v1','audience':'grading','sourceRoot':str(execution/'tasks'),'sourceCommit':git(public,'rev-parse','HEAD'),'projects':[{'exerciseId':'exr-demo','projectRoot':'projects/demo'}],'replacementRoots':['projects/demo/'+p for p in ['student','reference','tests','rubric.md','contract.md']],'files':files,'sourceDocuments':{'lab.qmd':hashlib.sha256(b'PUBLIC').hexdigest()},'commonSources':{'shared.txt':hashlib.sha256(b'COMMON').hexdigest()},'declarationsHash':'a'*64}
  write(core/'materialization.json',json.dumps(manifest));return public,execution,core,root/'stage',root/'receipt.json',manifest
 def test_distinct_generated_owner_preserves_real_manifest(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,receipt,m=self.fixture(Path(d));before=(c/'materialization.json').read_bytes();value=stage.prepare(p,'tasks',c,out,receipt)
   self.assertEqual(value['publicBase'],{'repository':'https://example.invalid/course.git','commit':git(p,'rev-parse','HEAD'),'book':'tasks'})
   self.assertEqual(value['materialization']['sha256'],hashlib.sha256(before).hexdigest());self.assertEqual((c/'materialization.json').read_bytes(),before)
   self.assertEqual((out/'tasks/projects/demo/student/seed/data.txt').read_text(),'INITIAL_ONLY');self.assertEqual(git(p,'status','--porcelain','--untracked-files=all'),'');self.assertNotEqual(git(e,'status','--porcelain','--untracked-files=all'),'');stage.validate(out,receipt)
 def test_distinct_owner_rejects_unbound_inputs_before_write(self):
  def replace_tree(p,e,c,m):
   empty=subprocess.check_output(['git','hash-object','-t','tree','-w','--stdin'],cwd=e,input=b'').decode().strip()
   replacement=git(e,'-c','user.name=F','-c','user.email=f@example.invalid','commit-tree',empty,'-m','Other tree')
   git(e,'replace','HEAD',replacement)
  changes={
   'head':lambda p,e,c,m:git(e,'-c','user.name=F','-c','user.email=f@example.invalid','commit','--allow-empty','-qm','Other HEAD'),
   'same-head-replaced-tree':replace_tree,
   'origin':lambda p,e,c,m:git(e,'remote','set-url','origin','https://other.invalid/course.git'),
   'tracked-bytes':lambda p,e,c,m:write(e/'tasks/lab.qmd','DRIFT'),
   'tracked-mode':lambda p,e,c,m:(e/'tasks/lab.qmd').chmod(0o755),
   'tracked-private-mode':lambda p,e,c,m:(e/'tasks/lab.qmd').chmod(0o600),
   'index':lambda p,e,c,m:git(e,'rm','--cached','tasks/lab.qmd'),
   'assume-unchanged':lambda p,e,c,m:git(e,'update-index','--assume-unchanged','tasks/lab.qmd'),
   'skip-worktree':lambda p,e,c,m:git(e,'update-index','--skip-worktree','tasks/lab.qmd'),
   'missing-seed':lambda p,e,c,m:(e/'tasks/projects/demo/student/seed/data.txt').unlink(),
   'changed-seed':lambda p,e,c,m:write(e/'tasks/projects/demo/student/seed/data.txt','DRIFT'),
   'extra-seed':lambda p,e,c,m:write(e/'tasks/projects/demo/student/seed/extra','EXTRA'),
   'untracked-outside':lambda p,e,c,m:write(e/'EXTRA','EXTRA'),
   'ignored-outside':lambda p,e,c,m:write(e/'ignored/EXTRA','EXTRA'),
   'ignored-git-outside':lambda p,e,c,m:write(e/'ignored/.git/HEAD','ref: refs/heads/main\n'),
   'empty-directory-outside':lambda p,e,c,m:(e/'ignored').mkdir(),
   'symlink':lambda p,e,c,m:(e/'ignored').symlink_to(p,target_is_directory=True),
   'hardlink':lambda p,e,c,m:((e/'tasks/projects/demo/student/seed/data.txt').unlink(),os.link(c/'projects/demo/student/seed/data.txt',e/'tasks/projects/demo/student/seed/data.txt')),
   'source-document':lambda p,e,c,m:m['sourceDocuments'].update({'missing.qmd':'a'*64}),
   'common':lambda p,e,c,m:m['commonSources'].update({'shared.txt':'a'*64}),
   'document-common-conflict':lambda p,e,c,m:(m['sourceDocuments'].update({'shared.txt':'a'*64})),
   'untracked-common':lambda p,e,c,m:m['files'][1].update(origin='common'),
   'foreign-source':lambda p,e,c,m:m['files'][0].update(source=str(p/'tasks/projects/demo/student/main.txt')),
   'owner-root':lambda p,e,c,m:m.update(sourceRoot=str(e)),
   'manifest-hash':lambda p,e,c,m:m['files'][0].update(sha256='a'*64),
   'extra-core':lambda p,e,c,m:write(c/'EXTRA','EXTRA'),
  }
  for name,change in changes.items():
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m=self.fixture(Path(d));change(p,e,c,m);write(c/'materialization.json',json.dumps(m))
    with self.assertRaises((stage.StageError,OSError)):stage.prepare(p,'tasks',c,out,r)
    self.assertFalse(out.exists());self.assertFalse(r.exists())
 def test_execution_output_and_receipt_collisions_rejected(self):
  for which in ['output','receipt']:
   with self.subTest(which=which),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m=self.fixture(Path(d))
    if which=='output':out=e/'new-stage'
    else:r=e/'new-receipt.json'
    with self.assertRaises(stage.StageError):stage.prepare(p,'tasks',c,out,r)
    self.assertFalse(out.exists());self.assertFalse(r.exists())
 def test_ordinary_same_owner_git_worktree(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m=self.fixture(Path(d));worktree=Path(d)/'worktree';git(p,'worktree','add','--detach',str(worktree),'HEAD')
   removed=[f for f in m['files'] if '/seed/' in f['target']]
   for f in removed:(c/f['target']).unlink()
   m['files']=[f for f in m['files'] if f not in removed];m['sourceRoot']=str(worktree/'tasks')
   for f in m['files']:f['source']=str(worktree/Path(f['source']).relative_to(e))
   write(c/'materialization.json',json.dumps(m));value=stage.prepare(worktree,'tasks',c,out,r);stage.validate(out,r);self.assertEqual(value['publicBase']['commit'],git(p,'rev-parse','HEAD'))
 def empty_git_directories(self,e):
  base=e/'tasks/projects/demo/student/seed/.git';paths=[base/x for x in ['objects/info','objects/pack','refs/tags']]
  # Родители реальных objects/refs должны уже принадлежать file-only receipt.
  return paths
 def test_fixed_empty_git_directories_and_prepost_identity(self):
  changes={
   'positive':lambda path:None,
   'arbitrary':lambda path:(path.parent/'extra').mkdir(),
   'child-file':lambda path:write(path/'EXTRA','EXTRA'),
   'child-directory':lambda path:(path/'extra').mkdir(),
   'mode':lambda path:path.chmod(0o700),
   'type':lambda path:(path.rmdir(),path.write_text('FILE')),
   'symlink':lambda path:(path.rmdir(),path.symlink_to(path.parent,target_is_directory=True)),
  }
  for name,change in changes.items():
   with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m=self.fixture(Path(d));base=e/'tasks/projects/demo/student/seed/.git'
    # Оба базовых родителя — ancestors настоящих M files, не новое разрешение.
    for leaf in ['objects/aa/known','refs/heads/main']:
     src=base/leaf;write(src,'SEED');target='projects/demo/student/seed/.git/'+leaf;write(c/target,'SEED');m['files'].append({'target':target,'source':str(src),'sha256':hashlib.sha256(b'SEED').hexdigest(),'origin':'public'})
    paths=self.empty_git_directories(e)
    for path in paths:path.mkdir(mode=0o755)
    write(c/'materialization.json',json.dumps(m));change(paths[0])
    if name=='positive':stage.prepare(p,'tasks',c,out,r);stage.validate(out,r)
    else:
     with self.assertRaises(stage.StageError):stage.prepare(p,'tasks',c,out,r)
     self.assertFalse(out.exists());self.assertFalse(r.exists())
  for drift in ['replace','remove','add-presence','mode','child']:
   with self.subTest(drift=drift),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m=self.fixture(Path(d));base=e/'tasks/projects/demo/student/seed/.git';path=base/'refs/tags';write(base/'refs/heads/main','SEED');target='projects/demo/student/seed/.git/refs/heads/main';write(c/target,'SEED');m['files'].append({'target':target,'source':str(base/'refs/heads/main'),'sha256':hashlib.sha256(b'SEED').hexdigest(),'origin':'public'});write(c/'materialization.json',json.dumps(m))
    if drift!='add-presence':path.mkdir(mode=0o755)
    original=stage.validate
    def mutate(*args,**kwargs):
     if drift=='replace':path.rename(Path(d)/'retired');path.mkdir(mode=0o755)
     elif drift=='remove':path.rmdir()
     elif drift=='add-presence':path.mkdir(mode=0o755)
     elif drift=='mode':path.chmod(0o700)
     else:write(path/'ADDED','ADDED')
     return original(*args,**kwargs)
    with patch.object(stage,'validate',side_effect=mutate):
     with self.assertRaises(stage.StageError):stage.prepare(p,'tasks',c,out,r)
    self.assertFalse(out.exists());self.assertFalse(r.exists())
 def test_distinct_owner_prepost_drift_cleans_only_new_outputs(self):
  for scope in ['public','execution','core']:
   with self.subTest(scope=scope),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m=self.fixture(Path(d));original=stage.validate
    def drift(*args,**kwargs):
     write({'public':p/'tasks/lab.qmd','execution':e/'tasks/projects/demo/student/seed/ADDED','core':c/'ADDED'}[scope],'DRIFT');return original(*args,**kwargs)
    with patch.object(stage,'validate',side_effect=drift):
     with self.assertRaises(stage.StageError):stage.prepare(p,'tasks',c,out,r)
    self.assertFalse(out.exists());self.assertFalse(r.exists());self.assertTrue(p.exists() and e.exists() and c.exists())
