"""Закрытая host preparation; installer/JVM/Gradle на host не исполняются."""
from pathlib import Path
import argparse
import copy
import ctypes
import hashlib
import importlib.util
import json
import io
import re
import tarfile
import lzma
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
TOOLCHAIN='images/java25-grader/toolchain'
FINGERPRINT='F6ECB3762474EDA9D21B7022871920D1991BC93C'
EXPECTED_LOCK='c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca'
HARDENED_LOCK='bcde4c1c54c4c11cc6e55381a6bbf53df97968e644c986d3aa32676c552f231f'
RUNNER='8f7d1e4d32217416c5c98e4f108a7997a9fdb47ab87736923048528511d4d08e'
COMPONENTS={'lib/libmanagement.so','lib/libmanagement_ext.so','lib/libmanagement_agent.so'}

def require(value,message):
 if not value:raise ValueError(message)
def digest_bytes(value):return hashlib.sha256(value).hexdigest()
def encode(value):return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
def safe_parent(path):
 require('..' not in Path(path).parts,'Parent traversal refused')
 path=Path(os.path.abspath(path))
 for parent in [*reversed(path.parents),path]:
  s=parent.lstat();require(stat.S_ISDIR(s.st_mode) and s.st_uid in (0,os.geteuid()),'Unsafe parent identity: '+str(parent))
  # A sticky root-owned /tmp may be an ancestor, never an output/cache parent.
  require(not s.st_mode&0o022 or (parent==Path('/tmp') and s.st_uid==0 and s.st_mode&stat.S_ISVTX),'Writable parent: '+str(parent))
 return path

def read_regular(path,pin=None):
 path=Path(path);safe_parent(path.parent)
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  before=os.fstat(fd);require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_uid in (0,os.geteuid()) and not before.st_mode&0o022,'Unsafe regular input: '+str(path))
  if pin:require(before.st_size==pin['bytes'],'Input size mismatch: '+str(path))
  require(before.st_size<=256*1024*1024,'Input too large')
  chunks=[];left=before.st_size+1
  while left:
   b=os.read(fd,min(left,1048576))
   if not b:break
   chunks.append(b);left-=len(b)
  data=b''.join(chunks);after=os.fstat(fd)
  require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and len(data)==before.st_size,'Input changed while reading')
  require(path.lstat()==after,'Input pathname changed')
  if pin:require(digest_bytes(data)==pin['sha256'],'Input hash mismatch: '+str(path))
  return data
 finally:os.close(fd)

def file_record(path):
 data=read_regular(path);return dict(bytes=len(data),sha256=digest_bytes(data),mode=oct(stat.S_IMODE(path.lstat().st_mode)))
def verify_files(root,expected):
 safe_parent(root);require(stat.S_IMODE(root.lstat().st_mode)==0o700,'Private context root mode required');actual={}
 for path in sorted(root.rglob('*')):
  info=path.lstat()
  if stat.S_ISDIR(info.st_mode):
   safe_parent(path);require(stat.S_IMODE(info.st_mode)==0o700,'Private context directory mode required');continue
  actual[path.relative_to(root).as_posix()]=file_record(path)
 require(actual==expected,'Context missing/extra/changed file or mode')
 # Empty extra directories also lie outside the declared payload closure.
 parents={str(Path(n).parent) for n in expected}
 allowed={'.'}
 for name in parents:
  q=Path(name)
  allowed.add(str(q));allowed.update(str(x) for x in q.parents)
 require(all(p.relative_to(root).as_posix() in allowed for p in root.rglob('*') if p.is_dir()),'Extra context directory')

def publish_new(stage,output):
 safe_parent(output.parent)
 libc=ctypes.CDLL(None,use_errno=True);rename=libc.renameat2
 rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];rename.restype=ctypes.c_int
 if rename(-100,os.fsencode(stage),-100,os.fsencode(output),1):
  err=ctypes.get_errno();raise OSError(err,os.strerror(err),str(output))

def source_identity(root):
 safe_parent(root)
 def git(*args):
  p=subprocess.run(['git','-C',str(root),*args],capture_output=True,check=True,timeout=15)
  require(len(p.stdout)<=8*1024*1024,'Git output limit');return p.stdout
 require(not git('status','--porcelain=v1','--untracked-files=all'),'Clean source checkout required')
 commit=git('rev-parse','HEAD').decode().strip();require(len(commit)==40 and all(c in '0123456789abcdef' for c in commit),'Invalid source commit')
 return {'commit':commit,'tree':git('rev-parse','HEAD^{tree}').decode().strip()}

def load_normalizer(root):
 path=root/'tools/prepare_native_jdk.py';spec=importlib.util.spec_from_file_location('native_jdk_preparation',path);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);return module

def generated_locks(canonical):
 value=copy.deepcopy(canonical)
 require(value['status']=='prepared-completion-awaiting-image-admission' and len(value['jdk']['files'])==319 and len(value['gradle']['files'])==716,'Canonical319/716 expected lock required')
 require(COMPONENTS<=set(value['jdk']['files']),'Missing complete JDK member')
 value['status']='image-admitted';expected=encode(value)
 for name in COMPONENTS:del value['jdk']['files'][name]
 hardened=encode(value)
 require(digest_bytes(expected)==EXPECTED_LOCK and digest_bytes(hardened)==HARDENED_LOCK,'Generated lock pin mismatch')
 return expected,hardened

def baked_view(root,expected,read=None):
 read=read or read_regular
 require(digest_bytes(expected)==EXPECTED_LOCK,'Unexpected generated lock')
 source=json.loads(read(root/'runtime-profiles.json'));profiles={}
 for name in ('java25-junit-v1','java25-mutation-v1'):
  profile=copy.deepcopy(source['profiles'][name]);profile.pop('image');profile['runnerSha256']=RUNNER
  for relative,pin in profile['files'].items():require(digest_bytes(read(root/profile['bundle']/relative))==pin,'Bundle pin mismatch')
  for relative,pin in profile['sharedFiles'].items():require(digest_bytes(read(root/relative))==pin,'Shared dependency mismatch')
  profile['sharedFiles']['runtime/gradle-jar-v1/toolchain-lock.json']=EXPECTED_LOCK;profiles[name]=profile
 native=copy.deepcopy(profiles['java25-junit-v1']);native['sharedFiles'].pop('runtime/gradle-jar-v1/toolchain-lock.json')
 for name in ('build.gradle','settings.gradle'):
  relative='runtime/gradle-jar-v1/'+name;native['sharedFiles'][relative]=digest_bytes(read(root/relative))
 native['sharedFiles']['runtime/gradle-jar-v1/toolchain-lock.json']=EXPECTED_LOCK;profiles['java25-gradle-junit-v1']=native
 require(digest_bytes(read(root/'images/java25-grader/grade.py'))==RUNNER,'Runner drift')
 return {'schemaVersion':1,'profiles':profiles}

def _fish_view(root,read=None):
 read=read or read_regular
 source=json.loads(read(root/'runtime-profiles.json'))
 fish=copy.deepcopy(source['profiles']['fish-git-v1']);fish.pop('image')
 bundle=root/fish['bundle']
 require({p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}==set(fish['files']),'Fish dependency closure changed')
 fish['runnerSha256']=digest_bytes(read(root/fish['runner']))
 fish['files']={name:digest_bytes(read(bundle/name)) for name in fish['files']}
 fish['sharedFiles']={name:digest_bytes(read(root/name)) for name in fish['sharedFiles']}
 return {'schemaVersion':1,'profiles':{'fish-git-v1':fish}}

def package_stanza(text,expected):
 selected=[]
 for paragraph in text.strip().split('\n\n'):
  fields={}
  for line in paragraph.splitlines():
   if not line or line[0].isspace():continue
   key,sep,value=line.partition(': ')
   require(bool(sep) and key not in fields,'Invalid/duplicate package field');fields[key]=value
  if fields.get('Package')==expected['Package']:selected.append(fields)
 require(len(selected)==1 and all(selected[0].get(k)==v for k,v in expected.items()),'Exact single package stanza required')
 return selected[0]

def verified_inrelease(keyring,inrelease):
 # An isolated empty GnuPG home prevents personal keyrings/configuration reads.
 with tempfile.TemporaryDirectory(prefix='native-gpgv-') as home:
  r=subprocess.run(['gpgv','--homedir',home,'--status-fd','2','--keyring',str(keyring),'--output','-',str(inrelease)],capture_output=True,timeout=20,env={'PATH':os.defpath,'LANG':'C','LC_ALL':'C'},stdin=subprocess.DEVNULL)
 require(r.returncode==0 and len(r.stdout)<=256*1024 and len(r.stderr)<=65536,'Signed InRelease verification failed')
 signatures=[line.split()[2] for line in r.stderr.decode().splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
 require(FINGERPRINT in signatures,'Unexpected signing fingerprint')
 return r.stdout.decode(),{'signingFingerprint':FINGERPRINT,'gpgvExit':r.returncode}

def authenticate_cache(root,cache,lock):
 safe_parent(cache);data={name:read_regular(cache/name,pin) for name,pin in lock['inputs'].items()}
 keyring=root/TOOLCHAIN/'ubuntu-archive-keyring.gpg';require(digest_bytes(read_regular(keyring))==lock['keyringSha256'],'Keyring drift')
 signed,proof=verified_inrelease(keyring,cache/'ubuntu-InRelease')
 entries=[];section=False
 for line in signed.splitlines():
  if line=='SHA256:':section=True;continue
  if section and not line.startswith(' '):section=False
  if section:
   fields=line.split()
   if len(fields)==3 and fields[2]=='universe/binary-amd64/Packages.xz':entries.append(fields)
 pin=lock['inputs']['ubuntu-Packages.xz'];require(entries==[[pin['sha256'],str(pin['bytes']),'universe/binary-amd64/Packages.xz']],'Signed Packages binding mismatch')
 decoder=lzma.LZMADecompressor();packages=decoder.decompress(data['ubuntu-Packages.xz'],max_length=32*1024*1024)
 require(decoder.eof and not decoder.unused_data,'Packages decompression limit/trailing data')
 stanza=package_stanza(packages.decode(),lock['package'])
 require(stanza['SHA256']==digest_bytes(data['openjdk-25-jre-headless.deb']) and int(stanza['Size'])==len(data['openjdk-25-jre-headless.deb']),'Signed package binding mismatch')
 proof.update(metadataSha256={name:digest_bytes(value) for name,value in data.items() if name.startswith('ubuntu-')},packageSHA256=stanza['SHA256'])
 return data,proof

class HTTPSOnly(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  require(newurl.startswith('https://'),'Non-HTTPS redirect refused')
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch_missing(cache,lock):
 if not cache.exists():safe_parent(cache.parent);cache.mkdir(mode=0o700)
 safe_parent(cache)
 opener=urllib.request.build_opener(HTTPSOnly())
 for name,pin in lock['inputs'].items():
  target=cache/name
  if os.path.lexists(target):read_regular(target,pin);continue
  require(pin['url'].startswith('https://'),'Fixed HTTPS input required')
  temp=cache/('.'+name+'.partial');fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);identity=os.fstat(fd)
  try:
   start=time.monotonic();total=0;h=hashlib.sha256()
   with os.fdopen(fd,'wb') as out,opener.open(pin['url'],timeout=30) as response:
    while True:
     require(time.monotonic()-start<=300,'Input fetch deadline')
     b=response.read(1048576)
     if not b:break
     total+=len(b);require(total<=pin['bytes'],'Oversized input');h.update(b);out.write(b)
   require(total==pin['bytes'] and h.hexdigest()==pin['sha256'],'Downloaded fixed input mismatch')
   # Hardlink CREATE_NEW only publishes the complete checked file; remove staging link before use.
   os.link(temp,target,follow_symlinks=False);temp.unlink()
  finally:
   if temp.exists():
    require(temp.lstat().st_ino==identity.st_ino,'Staging file identity drift');temp.unlink()

def public_sources(root):
 paths=[Path(x) for x in subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0') if x]
 selected=[p for p in paths if p.parts[0]=='runtime' or p.as_posix() in {'images/java25-grader/Dockerfile','images/java25-grader/grade.py','tools/prepare_native_jdk.py','images/fish-git-grader/grade.py','images/fish-git-grader/Dockerfile','schemas/grading-descriptor.schema.json'} or p.as_posix().startswith(TOOLCHAIN+'/') or p.as_posix().startswith('images/java25-grader/landlock/') or p.as_posix()=='tools/prepare_native_toolchain.py' or p.as_posix()=='VERSION' or p.as_posix()=='runtime-profiles.json' or p.as_posix()=='images/java25-grader/Dockerfile.dockerignore']
 return {p.as_posix():file_record(root/p) for p in selected}

def expected_payload_records(root):
 lock=json.loads(read_regular(root/TOOLCHAIN/'inputs.lock.json'));normalizer=load_normalizer(root)
 expected,hardened=generated_locks(json.loads(read_regular(root/'runtime/gradle-jar-v1/toolchain-lock.json')))
 values={'runtime-profiles.json':(encode(baked_view(root,expected)),0o644),'operator/hardened-toolchain-lock.json':(hardened,0o600),'operator/expected-toolchain-lock.json':(expected,0o600),'operator/completion-authority.json':(encode({'packageSHA256':normalizer.COMPLETION_PACKAGE_SHA256,'components':normalizer.COMPLETION_FILES}),0o600)}
 values['fish-runtime-profiles.json']=(encode(_fish_view(root)),0o644)
 for name in ('install-native.py','complete-native.py','source-inventory.json'):values['operator/'+name]=(read_regular(root/TOOLCHAIN/name),0o600)
 records={name:dict(bytes=len(data),sha256=digest_bytes(data),mode=oct(mode)) for name,(data,mode) in values.items()}
 records['gradle-9.8.0-bin.zip']={k:v for k,v in lock['inputs']['gradle-9.8.0-bin.zip'].items() if k in ('bytes','sha256')};records['gradle-9.8.0-bin.zip']['mode']='0o600'
 records['landlock_sandbox']=dict(bytes=lock['helperBytes'],sha256=lock['helperSha256'],mode='0o755')
 for name,value in normalizer.COMPLETION_FILES.items():records['operator/components/'+Path(name).name]=dict(value)
 return records

def validate_declared_payloads(root,declared):
 require(declared==expected_payload_records(root),'Prepared manifest cannot reauthorize changed public inputs')

def prepare(root,cache,fetch=False):
 require(sys.version_info>=(3,14),'Host Python3.14+ required for closed zstd package reader')
 before=source_identity(root);sources=public_sources(root);lock=json.loads(read_regular(root/TOOLCHAIN/'inputs.lock.json'))
 require(lock['schemaVersion']==1 and lock['platform']=='linux/amd64' and lock['signingFingerprint']==FINGERPRINT,'Unsupported administrative lock')
 require(set(lock['inputs'])=={'gradle-9.8.0-bin.zip','ubuntu-InRelease','ubuntu-Packages.xz','openjdk-25-jre-headless.deb'},'Closed input membership required')
 output=root/'.native-toolchain';require(not os.path.lexists(output),'Fresh output required')
 if fetch:fetch_missing(cache,lock)
 data,authentication=authenticate_cache(root,cache,lock)
 require(digest_bytes(read_regular(root/'tools/prepare_native_jdk.py'))==lock['normalizerSha256'],'Normalizer drift')
 normalizer=load_normalizer(root);require(lock['components']==normalizer.COMPLETION_FILES,'Component lock drift');expected,hardened=generated_locks(json.loads(read_regular(root/'runtime/gradle-jar-v1/toolchain-lock.json')))
 admission=read_regular(root/TOOLCHAIN/'source-inventory.json');require(digest_bytes(admission)==lock['sourceInventorySha256'],'Source inventory drift');normalizer._validate_production_admission(admission)
 parsed=normalizer._validate_completion_package(cache/'openjdk-25-jre-headless.deb',json.loads(hardened)['jdk']['files'])
 require(set(parsed['components'])==COMPONENTS,'Closed component set required')
 for name,value in parsed['components'].items():
  require(value[:6]==b'\x7fELF\x02\x01' and int.from_bytes(value[18:20],'little')==62,'Component ELF architecture mismatch')
  require(digest_bytes(value)==lock['componentELF'][Path(name).name]['sha256'],'Known ELF provenance drift')
 helper=read_regular(root/'images/java25-grader/landlock/landlock_sandbox.amd64',{'bytes':lock['helperBytes'],'sha256':lock['helperSha256']})
 require(digest_bytes(read_regular(root/'images/java25-grader/landlock/sandbox.c'))==lock['helperSourceSha256'],'Helper C drift')
 payloads={'runtime-profiles.json':(encode(baked_view(root,expected)),0o644),'gradle-9.8.0-bin.zip':(data['gradle-9.8.0-bin.zip'],0o600),'landlock_sandbox':(helper,0o755),'operator/source-inventory.json':(admission,0o600),'operator/hardened-toolchain-lock.json':(hardened,0o600),'operator/expected-toolchain-lock.json':(expected,0o600),'operator/completion-authority.json':(encode({'packageSHA256':normalizer.COMPLETION_PACKAGE_SHA256,'components':normalizer.COMPLETION_FILES}),0o600)}
 payloads['fish-runtime-profiles.json']=(encode(_fish_view(root)),0o644)
 for name in ('install-native.py','complete-native.py'):payloads['operator/'+name]=(read_regular(root/TOOLCHAIN/name),0o600)
 for name,value in parsed['components'].items():payloads['operator/components/'+Path(name).name]=(value,0o644)
 require(len(payloads)==13,'Exact generated payload count required')
 stage=Path(tempfile.mkdtemp(prefix='.native-toolchain-preparing-',dir=root))
 try:
  for name,(value,mode) in payloads.items():
   target=stage/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
   with target.open('xb') as out:out.write(value)
   target.chmod(mode)
  files={name:dict(bytes=len(value),sha256=digest_bytes(value),mode=oct(mode)) for name,(value,mode) in payloads.items()};validate_declared_payloads(root,files);verify_files(stage,files)
  require(public_sources(root)==sources,'Source inputs changed during preparation');require(source_identity(root)==before,'Source checkout changed during preparation')
  require({name:digest_bytes(read_regular(cache/name,lock['inputs'][name])) for name in data}=={name:digest_bytes(value) for name,value in data.items()},'Cache changed during preparation')
  version=read_regular(root/'VERSION').decode().strip();require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version),'Candidate semantic version required')
  manifest=dict(version=version,schemaVersion=1,kind='prepared-public-native-toolchain-not-image-admission',source=before,sourceFiles=sources,files=files,authentication=authentication,overlap=parsed['overlap'],buildOrJavaExecuted=False,actualImageAdmitted=False)
  with (stage/'context-manifest.json').open('xb') as out:out.write(encode(manifest))
  (stage/'context-manifest.json').chmod(0o600);publish_new(stage,output)
  return manifest
 finally:
  if stage.exists():shutil.rmtree(stage)

def verify_context(root):
 identity=source_identity(root);out=root/'.native-toolchain';manifest=json.loads(read_regular(out/'context-manifest.json'))
 require(manifest['version']==read_regular(root/'VERSION').decode().strip(),'Prepared candidate version mismatch')
 require(manifest['source']==identity and manifest['sourceFiles']==public_sources(root),'Prepared context/source mismatch')
 validate_declared_payloads(root,manifest['files'])
 files=dict(manifest['files']);files['context-manifest.json']=file_record(out/'context-manifest.json');verify_files(out,files)
 require(set(manifest['files'])=={'runtime-profiles.json','fish-runtime-profiles.json','gradle-9.8.0-bin.zip','landlock_sandbox','operator/source-inventory.json','operator/hardened-toolchain-lock.json','operator/expected-toolchain-lock.json','operator/completion-authority.json','operator/install-native.py','operator/complete-native.py',*[('operator/components/'+Path(n).name) for n in COMPONENTS]},'Unexpected prepared payload')
 expected,hardened=generated_locks(json.loads(read_regular(root/'runtime/gradle-jar-v1/toolchain-lock.json')))
 require(read_regular(out/'runtime-profiles.json')==encode(baked_view(root,expected)),'Baked dependency drift')
 require(read_regular(out/'operator/expected-toolchain-lock.json')==expected and read_regular(out/'operator/hardened-toolchain-lock.json')==hardened,'Prepared lock drift')
 return manifest

def write_context_tar(root,output,members):
 safe_parent(output.parent)
 if os.path.lexists(output):raise FileExistsError(str(output))
 fd,name=tempfile.mkstemp(prefix='.native-context-',dir=output.parent);stage=Path(name)
 try:
  with os.fdopen(fd,'wb') as stream,tarfile.open(fileobj=stream,mode='w',format=tarfile.PAX_FORMAT) as archive:
   directories=set()
   for name in members:
    require(not Path(name).is_absolute() and '..' not in Path(name).parts,'Unsafe context member')
    directories.update(str(p) for p in Path(name).parents if str(p)!='.')
   for name in sorted(directories):
    entry=tarfile.TarInfo(name);entry.type=tarfile.DIRTYPE;entry.mode=0o700 if name.startswith('.native-toolchain') else 0o755;archive.addfile(entry)
   for name,record in sorted(members.items()):
    data=read_regular(root/name,record);require(oct(stat.S_IMODE((root/name).lstat().st_mode))==record['mode'],'Context source mode drift')
    entry=tarfile.TarInfo(name);entry.mode=int(record['mode'],8);entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
  publish_new(stage,output)
 finally:
  if stage.exists():stage.unlink()

def build_context(root,output):
 manifest=verify_context(root);files={name:record for name,record in manifest['sourceFiles'].items() if name.startswith('runtime/') or name in ('images/java25-grader/Dockerfile','images/java25-grader/grade.py','tools/prepare_native_jdk.py')}
 files.update({'.native-toolchain/'+name:record for name,record in manifest['files'].items()});files['.native-toolchain/context-manifest.json']=file_record(root/'.native-toolchain/context-manifest.json')
 before=source_identity(root);write_context_tar(root,output,files)
 require(source_identity(root)==before,'Source changed while creating context archive');verify_context(root)
 return {'source':before,'files':files,'archive':file_record(output)}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cache',type=Path,default=ROOT/'.native-toolchain-cache');p.add_argument('--fetch',action='store_true',help='Явно получить только отсутствующие fixed HTTPS inputs');p.add_argument('--verify-context',action='store_true');p.add_argument('--write-build-context',type=Path,help='Новый закрытый public TAR для genuine Dockerfile build stdin');args=p.parse_args(argv)
 try:
  require(sum([args.fetch,args.verify_context,bool(args.write_build_context)])<=1,'Fetch, verify and context emission are separate commands')
  result=build_context(ROOT,args.write_build_context.absolute()) if args.write_build_context else verify_context(ROOT) if args.verify_context else prepare(ROOT,args.cache.absolute(),args.fetch)
  print(json.dumps({'source':result['source'],'payloadFiles':len(result['files']),'actualImageAdmitted':False},sort_keys=True));return 0
 except (ValueError,OSError,subprocess.SubprocessError) as error:
  print('Preparation refused: '+str(error),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
