"""Четыре роли UNIT-поставки через настоящий source-bound assembly consumer."""
from pathlib import Path
import hashlib,json,subprocess,tempfile,unittest
from release_assembly_fixtures import AssemblyFixture,load,ROOT,put,write_json,IMAGES

WORKSPACE='ghcr.io/unit-example/sp-git-workspace@sha256:'+'6'*64
BASE='docker.io/prairielearn/workspace-vscode-base@sha256:cdad0b1fd89a3e019efca29c66768ffa2f7b4f99dbfe3016e2667f6769b90600'

class WorkspaceReleaseAssembly(unittest.TestCase):
 def fixture(self,name):
  f=AssemblyFixture(name);pub=load('workspace_assembly_publisher',ROOT/'tools/publish-receipt.py')
  images={**IMAGES,'workspace':WORKSPACE}
  # AssemblyFixture уже наложила опубликованные overlays; derivation читает
  # канонические Git blobs так же, как настоящий Context.GitSource.read.
  def source(path):
   relative=Path(path).relative_to(f.platform).as_posix()
   return subprocess.check_output(['git','-C',str(f.platform),'show','HEAD:'+relative])
  registry,lock=pub.derive_release_registry(f.platform,images,source,delivery_version=4)
  encoded=pub.preparation.encode(registry)
  receipt={'schemaVersion':3,'sourceCommit':f.commit,'version':'2.3.0','images':images,'deliverySchemaVersion':4,'resultsSchemaVersion':2,'runtimeProfilesSha256':hashlib.sha256(encoded).hexdigest()}
  put(f.assets/'published-runtime-profiles.json',encoded,0o600)
  put(f.assets/'published-toolchain-lock.json',lock,0o600)
  put(f.assets/'runtime-image.json',pub.preparation.encode(receipt),0o600)
  # Полная роль необходима даже когда исходный manifest ошибочно её потерял:
  # настоящий Context должен принять корректную source-declared поставку.
  f.images['spGitWorkspace']={**json.loads((f.platform/'images.lock.json').read_bytes()).get('spGitWorkspace',{'baseImage':BASE,'status':'UNIT ONLY'}),'image':WORKSPACE,'sourceCommit':f.commit,'version':'2.3.0'}
  f.images['releaseAssembly']['assets']={n:hashlib.sha256((f.assets/n).read_bytes()).hexdigest()for n in ['runtime-image.json','published-runtime-profiles.json','published-toolchain-lock.json']}
  write_json(f.assets/'images.lock.json',f.images,0o600)
  put(f.platform/'runtime-profiles.json',encoded)
  put(f.platform/'runtime/gradle-jar-v1/toolchain-lock.json',lock)
  return f
 def context(self,f):
  return load('workspace_closed_assembly',ROOT/'tools/release_assembly.py').Context(f.platform,f.assets/'images.lock.json')
 def test_four_role_source_assembly_accepts_workspace_and_rechecks(self):
  with tempfile.TemporaryDirectory() as name:
   f=self.fixture(name);context=self.context(f)
   self.assertEqual(context.delivery_schema_version,4)
   self.assertEqual(context.registry['workspaceImages']['sp-git-workspace-v1']['image'],WORKSPACE)
   self.assertEqual(context.images['spGitWorkspace']['image'],WORKSPACE)
   context.recheck()
 def test_missing_workspace_actual_role_refuses(self):
  with tempfile.TemporaryDirectory() as name:
   f=self.fixture(name);del f.images['spGitWorkspace'];write_json(f.assets/'images.lock.json',f.images,0o600)
   with self.assertRaises(ValueError):self.context(f)
 def test_different_workspace_digest_refuses_before_assembly(self):
  with tempfile.TemporaryDirectory() as name:
   f=self.fixture(name);f.images['spGitWorkspace']['image']=WORKSPACE.replace('6'*64,'7'*64);write_json(f.assets/'images.lock.json',f.images,0o600)
   with self.assertRaisesRegex(ValueError,'actual image source/version/digest differs'):self.context(f)

if __name__=='__main__':unittest.main()
