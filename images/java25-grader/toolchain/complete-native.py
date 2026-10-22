"""Trusted same-build completion AFTER original immutable316 normalization."""
from pathlib import Path
import hashlib,importlib.util,json,os,pwd,grp,stat,subprocess,sys
ROOT=Path('/platform');OPERATOR=Path('/operator')
def require(value,message):
 if not value:raise RuntimeError(message)
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
require(os.geteuid()==0,'Trusted supervisor UID0 required')
for p in (ROOT,OPERATOR,Path('/javagrader')):
 s=p.lstat();require(stat.S_ISDIR(s.st_mode) and s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o700,'Private root drift')
normalizer=load('prepare_native_jdk',ROOT/'tools/prepare_native_jdk.py')
old_bytes=(ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').read_bytes()
require(hashlib.sha256(old_bytes).hexdigest()=='bcde4c1c54c4c11cc6e55381a6bbf53df97968e644c986d3aa32676c552f231f','Named hardened316 lock drift')
old=json.loads(old_bytes)
require(len(old['jdk']['files'])==316 and old['jdk']['home']=='/opt/native-jdk','Expected hardened316 parent')
receipt_bytes=(OPERATOR/'normalization-receipt.json').read_bytes();receipt=json.loads(receipt_bytes)
require(receipt['normalizedFiles']==old['jdk']['files'] and receipt['actualCopyCreated'],'Original316 receipt mismatch')
require(normalizer._portable(normalizer._snapshot(normalizer.SOURCE_HOME,normalizer._Policy()))==normalizer._portable(receipt['sourceAfter']),'Original hardened source/receipt drift')
authority_bytes=(OPERATOR/'completion-authority.json').read_bytes();authority=json.loads(authority_bytes)
require(authority['packageSHA256']==normalizer.COMPLETION_PACKAGE_SHA256 and authority['components']==normalizer.COMPLETION_FILES,'Completion provenance drift')
expected_bytes=(OPERATOR/'expected-toolchain-lock.json').read_bytes();expected=json.loads(expected_bytes)
relation=json.loads(json.dumps(old));relation['jdk']['files'].update(normalizer.COMPLETION_FILES)
require(expected==relation and len(expected['jdk']['files'])==319,'Exact316plus3 expected lock required')
try:pwd.getpwnam('nativebuild')
except KeyError:pass
else:raise RuntimeError('Unadmitted preexisting build account')
try:grp.getgrnam('nativebuild')
except KeyError:pass
else:raise RuntimeError('Unadmitted preexisting build group')
for argv in [['/usr/sbin/groupadd','--system','nativebuild'],['/usr/sbin/useradd','--system','--gid','nativebuild','--no-create-home','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','nativebuild']]:
 subprocess.run(argv,check=True,timeout=5,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'},stdin=subprocess.DEVNULL)
role=pwd.getpwnam('nativebuild');group=grp.getgrnam('nativebuild')
require(role.pw_uid!=0 and role.pw_gid==group.gr_gid!=0,'Allocated role invalid')
completion=normalizer._complete_build_jdk(OPERATOR/'components',old['jdk']['files'],group.gr_gid)
require(completion['completedAfter']['files']==expected['jdk']['files'],'Actual completed319 mismatch')
require((OPERATOR/'normalization-receipt.json').read_bytes()==receipt_bytes,'Original316 receipt modified')
(ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').write_bytes(expected_bytes)
(ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').chmod(0o644)
grader=load('image_grader',ROOT/'images/java25-grader/grade.py');roles=grader._role_records();grader._build_tree_state(roles);grader._hardened_tool_state();grader._verify_landlock_helper()
completion.update(accessRoles=roles,normalizationReceiptSha256=hashlib.sha256(receipt_bytes).hexdigest(),installedLockSha256=hashlib.sha256(expected_bytes).hexdigest(),originalGradingHome=str(grader.HARDENED_JDK),preparationSourceSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),completionAuthoritySha256=hashlib.sha256(authority_bytes).hexdigest(),executedJava=False,executedGradle=False,executedLandlock=False)
with (OPERATOR/'completion-receipt.json').open('x') as f:
 (OPERATOR/'completion-receipt.json').chmod(0o600);json.dump(completion,f,sort_keys=True);f.write('\n')
for p in (OPERATOR/'components').iterdir():p.unlink()
(OPERATOR/'components').rmdir()
print(json.dumps({'kind':'complete319-private-build-JDK','accessRoles':roles,'normalizationReceiptUnchanged':True,'installedLockSha256':completion['installedLockSha256'],'nativeImageProof':False}))
