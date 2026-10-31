"""Typed Workspace authority: synthetic assets, настоящий local Context/source replay."""
import copy,hashlib,json,tempfile,unittest
from release_assembly_fixtures import AssemblyFixture,load,ROOT,IMAGES,git,write_json,put
class Delivery4Assets(unittest.TestCase):
 def test_source_asset_bound_registry2_and_legacy_dispatch(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=AssemblyFixture(tmp);assembly=load('delivery4_unit_assembly',ROOT/'tools/release_assembly.py');pub=load('delivery4_unit_publisher',ROOT/'tools/publish-receipt.py')
   old=assembly.Context(f.platform,f.assets/'images.lock.json');self.assertEqual(old.delivery_schema_version,3);self.assertNotIn('workspaceImages',old.registry)
   workspace='ghcr.io/unit-example/sp-git-workspace@sha256:'+'7'*64
   images={**IMAGES,'workspace':workspace}
   with self.assertRaises(ValueError):pub.derive_release_registry(f.platform,images,delivery_version=3)
   # New source explicitly declares the role. No actual production pin is changed.
   for n in ('runtime-profiles.json','runtime/gradle-jar-v1/toolchain-lock.json'):put(f.platform/n,__import__('subprocess').check_output(['git','show','HEAD:'+n],cwd=f.platform))
   source=json.loads((f.platform/'images.lock.json').read_bytes());source['spGitWorkspace']={'image':workspace,'status':'UNIT ONLY','sourceCommit':'0'*40,'version':'2.3.0'};write_json(f.platform/'images.lock.json',source)
   git(f.platform,'add','images.lock.json');git(f.platform,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT typed Workspace role');git(f.platform,'tag','-f','v2.3.0');f.commit=git(f.platform,'rev-parse','HEAD');f.tree=git(f.platform,'rev-parse','HEAD^{tree}')
   registry,lock=pub.derive_release_registry(f.platform,images,delivery_version=4);self.assertEqual(set(registry['profiles']),set(old.registry['profiles']));self.assertEqual(registry['workspaceImages'],{'sp-git-workspace-v1':{'image':workspace}})
   prep=pub.preparation;raw=prep.encode(registry);receipt={'schemaVersion':3,'sourceCommit':f.commit,'version':'2.3.0','images':images,'deliverySchemaVersion':4,'resultsSchemaVersion':2,'runtimeProfilesSha256':hashlib.sha256(raw).hexdigest()}
   for n,data in [('runtime-image.json',prep.encode(receipt)),('published-runtime-profiles.json',raw),('published-toolchain-lock.json',lock)]:put(f.assets/n,data,0o600)
   actual=copy.deepcopy(f.images);actual['spGitWorkspace']=dict(source['spGitWorkspace'],sourceCommit=f.commit);actual['releaseAssembly'].update(sourceCommit=f.commit,sourceTree=f.tree)
   for key in ('javaGrader','fishGrader','communityGateway'):actual[key]['sourceCommit']=f.commit
   actual['releaseAssembly']['assets']={n:hashlib.sha256((f.assets/n).read_bytes()).hexdigest() for n in actual['releaseAssembly']['assets']};write_json(f.assets/'images.lock.json',actual,0o600)
   put(f.platform/'runtime-profiles.json',raw);put(f.platform/'runtime/gradle-jar-v1/toolchain-lock.json',lock)
   context=assembly.Context(f.platform,f.assets/'images.lock.json');context.recheck();self.assertEqual(context.delivery_schema_version,4);self.assertEqual(context.registry,registry)
   forged=copy.deepcopy(registry);forged['workspaceImages']['sp-git-workspace-v1']['image']='ghcr.io/unit-example/sp-git-workspace@sha256:'+'8'*64
   forgedraw=prep.encode(forged);put(f.assets/'published-runtime-profiles.json',forgedraw,0o600);receipt['runtimeProfilesSha256']=hashlib.sha256(forgedraw).hexdigest();put(f.assets/'runtime-image.json',prep.encode(receipt),0o600);actual['releaseAssembly']['assets']={n:hashlib.sha256((f.assets/n).read_bytes()).hexdigest() for n in actual['releaseAssembly']['assets']};write_json(f.assets/'images.lock.json',actual,0o600);put(f.platform/'runtime-profiles.json',forgedraw)
   with self.assertRaisesRegex(ValueError,'source-derived registry'):assembly.Context(f.platform,f.assets/'images.lock.json')
