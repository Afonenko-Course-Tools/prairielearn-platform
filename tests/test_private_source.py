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
