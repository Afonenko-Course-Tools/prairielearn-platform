"""Закрытая проверка released code tree и двух authenticated data overlays."""
from pathlib import Path
import copy,hashlib,importlib.util,json,os,re,stat,subprocess

REPOSITORY='https://github.com/Afonenko-Course-Tools/prairielearn-platform'
ASSETS=('runtime-image.json','published-runtime-profiles.json','published-toolchain-lock.json')
OVERLAYS={'runtime-profiles.json':'published-runtime-profiles.json','runtime/gradle-jar-v1/toolchain-lock.json':'published-toolchain-lock.json'}
HEX40=re.compile(r'[a-f0-9]{40}\Z');HEX64=re.compile(r'[a-f0-9]{64}\Z');SEMVER=re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\Z')
_spec=importlib.util.spec_from_file_location('assembly_publisher',Path(__file__).with_name('publish-receipt.py'))
publication=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(publication)
preparation=publication.preparation

def require(value,message):
 if not value:raise ValueError('Release assembly: '+message)
def digest(data):return hashlib.sha256(data).hexdigest()
def closed(value,keys):require(isinstance(value,dict) and set(value)==set(keys),'closed fields required: '+','.join(keys))
def hash64(value):return isinstance(value,str) and HEX64.fullmatch(value)
def git(root,*args):
 env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')};env.update(GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0')
 p=subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args],cwd=root,env=env,capture_output=True,timeout=30,check=True)
 require(len(p.stdout)<=16*1024**2,'Git output bound');return p.stdout

def real_directory(path,private=False):
 path=Path(path).absolute();require(path.resolve()==path and path.is_dir() and not path.is_symlink(),'real nonsymlink directory required')
 preparation.safe_parent(path)
 if private:require(stat.S_IMODE(path.stat().st_mode)==0o700,'assets root mode0700 required')
 return path

def read_asset(path):
 b=preparation.read_regular(path);require(stat.S_IMODE(path.lstat().st_mode)==0o600,'asset mode0600 required');return b

def stamp(path):
 s=path.lstat();return [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

class GitSource:
 def __init__(self,root,descriptor):
  self.root=real_directory(root);metadata=self.root/'.git';require(metadata.is_dir() and not metadata.is_symlink(),'contained ordinary Git metadata required')
  for f in metadata.rglob('*'):require(not f.is_symlink() and (f.is_dir() or f.is_file()),'unsafe Git metadata')
  require(not (metadata/'commondir').exists() and not (metadata/'objects/info/alternates').exists(),'external Git objects refused')
  self.commit=git(root,'rev-parse','HEAD').decode().strip();self.tree=git(root,'rev-parse','HEAD^{tree}').decode().strip()
  require(self.commit==descriptor['sourceCommit'] and self.tree==descriptor['sourceTree'],'source commit/tree mismatch')
  require(git(root,'rev-parse',descriptor['tag']+'^{commit}').decode().strip()==self.commit,'tag does not peel to source')
  require(git(root,'remote','get-url','origin').decode().strip() in (REPOSITORY,REPOSITORY+'.git'),'canonical origin required')
  require(Path(git(root,'rev-parse','--show-toplevel').decode().strip())==self.root,'Git invocation root mismatch')
  self.records={};self.blobs={}
  for item in git(root,'ls-tree','-rz','--full-tree',self.commit).split(b'\0'):
   if not item:continue
   meta,name=item.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode('utf-8','strict')
   relative_name(name);require(mode in ('100644','100755') and kind=='blob','source Git symlink/submodule refused')
   data=git(root,'cat-file','blob',oid);self.blobs[name]=data;self.records[name]={'mode':mode,'oid':oid,'sha256':digest(data)}
  require(set(OVERLAYS)<=self.records.keys(),'missing fixed source overlay targets')
  index={}
  for item in git(root,'ls-files','--stage','-z').split(b'\0'):
   if not item:continue
   meta,name=item.split(b'\t');mode,oid,stage=meta.decode().split();require(stage=='0','unmerged index refused');index[name.decode()]={'mode':mode,'oid':oid}
  require(index=={n:{k:v[k] for k in ('mode','oid')} for n,v in self.records.items()},'index differs from exact source tree')
  require(all(row.startswith(b'H ') for row in git(root,'ls-files','-v','-z').split(b'\0') if row),'index ignore/skip flags refused')
  self.version=self.read(root/'VERSION').decode().strip();require(self.version==descriptor['version'],'source VERSION mismatch')
 def read(self,path):
  name=Path(path).relative_to(self.root).as_posix();require(name in self.blobs,'unlisted canonical Git input');return self.blobs[name]
 def physical(self,overlays):
  directories={'.'}
  for n in self.records:directories.update(str(x) for x in Path(n).parents)
  actual={};stamps={}
  def walk(directory):
   for path in sorted(directory.iterdir()):
    name=path.relative_to(self.root).as_posix()
    if name=='.git':continue
    require(not path.is_symlink(),'source symlink refused')
    if path.is_dir():require(name in directories,'unknown/empty source directory');walk(path)
    else:
     require(name in self.records,'extra/ignored source file');data=preparation.read_regular(path);record=self.records[name];mode=int(record['mode'][-3:],8)
     require(stat.S_IMODE(path.lstat().st_mode)==mode,'source file mode mismatch')
     require(data==overlays.get(name,self.blobs[name]),'source/overlay bytes mismatch: '+name)
     actual[name]=dict(path=name,mode=record['mode'],sha256=digest(data));stamps[name]=stamp(path)
  walk(self.root);require(set(actual)==set(self.records),'missing source file')
  changed=git(self.root,'status','--porcelain=v1','--untracked-files=all').decode().splitlines()
  require(sorted(changed)==sorted(' M '+n for n in OVERLAYS),'actual dirty state must be exactly two unstaged overlays')
  return digest(json.dumps([actual[n] for n in sorted(actual)],ensure_ascii=False,separators=(',',':')).encode()),stamps

def relative_name(name):
 require(isinstance(name,str) and name and not name.startswith('/') and not any(c in name for c in '\\\0') and not any(x in ('','.','..') for x in name.split('/')),'invalid relative path');return name

def descriptor(value):
 closed(value,['schema','repository','sourceCommit','sourceTree','version','tag','assets'])
 require(value['schema']=='pl-platform-release-assets-v1' and value['repository']==REPOSITORY,'external release descriptor required')
 require(isinstance(value['sourceCommit'],str) and HEX40.fullmatch(value['sourceCommit']) and isinstance(value['sourceTree'],str) and HEX40.fullmatch(value['sourceTree']),'exact source identities required')
 require(isinstance(value['version'],str) and SEMVER.fullmatch(value['version']) and value['tag']=='v'+value['version'],'exact release version/tag required')
 closed(value['assets'],ASSETS);require(all(hash64(x) for x in value['assets'].values()),'asset SHA256 pins required')

class Context:
 def __init__(self,root,images_path):
  self.platform=Path(root).absolute();self.images_path=Path(images_path).absolute();require(self.images_path.name=='images.lock.json','fixed external images filename required')
  assets_root=real_directory(self.images_path.parent,True);require(not assets_root.is_relative_to(self.platform),'assets must remain outside assembly')
  require({p.name for p in assets_root.iterdir()}==set(ASSETS)|{'images.lock.json'},'asset directory inventory must be exactly four fixed files')
  raw=read_asset(self.images_path);images=json.loads(raw);require(isinstance(images,dict),'actual image view required');require('releaseAssembly' in images,'missing external releaseAssembly descriptor')
  d=images['releaseAssembly'];descriptor(d);source=GitSource(self.platform,d)
  payloads={name:read_asset(assets_root/name) for name in ASSETS}
  require({n:digest(b) for n,b in payloads.items()}==d['assets'],'published asset bytes differ from trusted pins')
  receipt=json.loads(payloads['runtime-image.json']);closed(receipt,['schemaVersion','sourceCommit','version','images','deliverySchemaVersion','resultsSchemaVersion','runtimeProfilesSha256'])
  require(receipt['schemaVersion']==2 and receipt['deliverySchemaVersion']==3 and receipt['resultsSchemaVersion']==2 and receipt['sourceCommit']==d['sourceCommit'] and receipt['version']==d['version'],'receipt2 source/version/protocol mismatch')
  registry,lock=publication.derive_release_registry(source.root,receipt['images'],source.read)
  require(publication.preparation.encode(registry)==payloads['published-runtime-profiles.json'] and lock==payloads['published-toolchain-lock.json'],'full source-derived registry/generated lock differs')
  require(receipt['runtimeProfilesSha256']==digest(payloads['published-runtime-profiles.json']),'receipt registry hash differs')
  canonical=json.loads(source.read(source.root/'images.lock.json'));require(set(images)==set(canonical)|{'releaseAssembly'} and images['schema']=='pl-images-v1','closed actual image view required')
  for key in set(canonical)-{'schema','javaGrader','fishGrader','communityGateway'}:require(images[key]==canonical[key],'unchanged image/source records differ')
  for role,key in [('java','javaGrader'),('fish','fishGrader'),('community','communityGateway')]:
   record=images[key];require(isinstance(record,dict) and set(canonical[key])<=set(record) and set(record)<=set(canonical[key])|{'localImage','localImageId'},'unknown image record field')
   for name,value in canonical[key].items():
    if name not in ('image','sourceCommit','version','localImage','localImageId','status'):require(record.get(name)==value,'image base/source metadata differs')
   require(record.get('image')==receipt['images'][role] and record.get('sourceCommit')==d['sourceCommit'] and record.get('version')==d['version'],'actual image source/version/digest differs')
   if 'localImage' in record:require(record['localImage']==record['image'].split('@')[0]+':'+d['version'],'actual version tag differs')
   if 'localImageId' in record:require(isinstance(record['localImageId'],str) and re.fullmatch(r'sha256:[a-f0-9]{64}',record['localImageId']),'actual config ID required')
  require('localImage' in images['javaGrader'] and 'localImageId' in images['javaGrader'],'Java actual pull/config view required')
  replacements={target:payloads[asset] for target,asset in OVERLAYS.items()}
  inventory_hash,source_stamps=source.physical(replacements)
  overlays={target:{'sourceSha256':source.records[target]['sha256'],'sha256':digest(data),'mode':source.records[target]['mode']} for target,data in replacements.items()}
  require(all(v['mode']=='100644' for v in overlays.values()),'fixed overlay source modes required')
  self._images=images;self.registry=registry;self.registry_path=assets_root/'published-runtime-profiles.json'
  self.builder={'repository':REPOSITORY,'commit':source.commit,'dirty':True,'mode':'release-assembly','releaseAssembly':{'schema':'pl-platform-release-assembly-v1','sourceTree':source.tree,'version':d['version'],'assets':copy.deepcopy(d['assets']),'imagesManifestSha256':digest(raw),'overlays':overlays,'inventoryHash':inventory_hash}}
  self._snapshot={'builder':copy.deepcopy(self.builder),'sourceStamps':source_stamps,'assetStamps':{n:stamp(assets_root/n) for n in (*ASSETS,'images.lock.json')}}
 @property
 def images(self):return copy.deepcopy(self._images)
 def recheck(self):
  again=Context(self.platform,self.images_path);require(again._snapshot==self._snapshot and again.registry==self.registry and again.images==self.images,'source/assets/view changed during operation')

def overlays_present(root):
 for name in OVERLAYS:
  canonical=git(root,'show','HEAD:'+name)
  if preparation.read_regular(Path(root)/name)!=canonical:return True
 return False

def for_build(root,registry):
 registry=Path(registry).absolute()
 if registry.name=='published-runtime-profiles.json':
  context=Context(root,registry.parent/'images.lock.json');require(registry==context.registry_path,'fixed registry sibling required');return context
 require(not overlays_present(root),'published asset context required; no downgrade to legacy');return None

def for_stage(root,images,images_path=None):
 if isinstance(images,dict) and 'releaseAssembly' in images:
  require(images_path is not None,'external images path required, not native provenance');context=Context(root,images_path);require(images==context.images,'parsed external view differs');return context
 require(not overlays_present(root),'historical source images cannot stage release assembly');return None

V2_FIELDS={'schema','source','builder','deliveryHash','sourceSnapshotHash','inventoryHash','platformImages','files'}
def validate_source(source,delivery):
 require(isinstance(source,dict) and source.get('dirty') is False,'clean source identity required')
 if source.get('mode')!='private-stage':
  closed(source,['repository','commit','dirty','book','instance']);require(HEX40.fullmatch(source['commit']) and re.fullmatch(r'https://[^/@\s]+/[^\s]+',source['repository']),'clean Git source repository/commit required')
 else:
  closed(source,['mode','publicBase','privateStage','stagingReceiptSha256','materialization','seedFiles','seedStorage','runtimeInventory','dirty','book','instance'])
  base=source['publicBase'];closed(base,['repository','commit','book']);require(isinstance(base['commit'],str) and HEX40.fullmatch(base['commit']) and isinstance(base['repository'],str) and re.fullmatch(r'https://[^/@\s]+/[^\s]+',base['repository']),'private publicBase identity')
  frozen=source['privateStage'];closed(frozen,['path','commit','tree','remotes']);require(isinstance(frozen['path'],str) and Path(frozen['path']).is_absolute() and HEX40.fullmatch(frozen['commit']) and HEX40.fullmatch(frozen['tree']) and frozen['remotes']==[],'private frozen identity required')
  require(base['book']==source['book'] and hash64(source['stagingReceiptSha256']) and source['seedStorage']=='receipt-hashed-outside-stage-index','private receipt/source binding required')
  m=source['materialization'];closed(m,['sha256','declarationsHash','files','commonSources']);require(hash64(m['sha256']) and hash64(m['declarationsHash']) and isinstance(m['files'],list) and bool(m['files']) and isinstance(m['commonSources'],dict),'private materialization evidence required')
  targets=set()
  for f in m['files']:
   require(isinstance(f,dict) and set(f)=={'source','target','origin','sha256'},'closed Core materialized file required');relative_name(f['target']);require(f['target'] not in targets and isinstance(f['source'],str) and f['source'] and f['origin'] in ('public','common','teacher') and hash64(f['sha256']),'invalid materialization file');targets.add(f['target'])
  for name,pin in m['commonSources'].items():relative_name(name);require(hash64(pin),'invalid common source hash')
  require(isinstance(source['seedFiles'],list) and len(source['seedFiles'])==len(set(source['seedFiles'])) and isinstance(source['runtimeInventory'],dict),'private seed/runtime inventory required')
  for name in source['seedFiles']:relative_name(name);require('.git' in name.split('/') and name.startswith(source['book']+'/'),'invalid declared seed')
  roots=[source['book']+'/_generated/',source['book']+'/.quarto/','.quarto/']
  for name,pin in source['runtimeInventory'].items():relative_name(name);require(any(name.startswith(prefix) for prefix in roots) and hash64(pin),'invalid private runtime capture')
 relative_name(source['book']);require(source['book']==delivery.get('bookRoot') and isinstance(source['instance'],str) and source['instance'] in delivery.get('instances',{}),'source book/instance differs from delivery')

def validate_provenance(provenance,delivery,context):
 closed(provenance,V2_FIELDS);require(provenance['schema']=='pl-provenance-v2' and context is not None,'v2 requires trusted external assembly context')
 require(provenance['builder']==context.builder and provenance['platformImages']==context.images,'native builder/images proof differs from trusted external pins')
 validate_source(provenance['source'],delivery)
 for key in ('deliveryHash','sourceSnapshotHash','inventoryHash'):require(hash64(provenance[key]) and provenance[key]==delivery.get(key),'native source/delivery identity mismatch')
 require(isinstance(provenance['files'],dict) and bool(provenance['files']),'nonempty native provenance inventory required')
 for name,pin in provenance['files'].items():relative_name(name);require(hash64(pin),'invalid native file pin')
