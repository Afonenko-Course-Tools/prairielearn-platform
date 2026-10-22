"""Finite synthetic image smoke. Real B8 acceptance remains a separate private check."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

IMAGE=os.environ.get('PL_NATIVE_PREPARED_IMAGE')
@unittest.skipUnless(IMAGE,'Set exact local PL_NATIVE_PREPARED_IMAGE after clean Dockerfile build')
class PreparedImageSmoke(unittest.TestCase):
 def command(self,*argv,timeout=30,input=None):
  r=subprocess.run(['docker',*argv],input=input,capture_output=True,timeout=timeout)
  self.assertEqual(r.returncode,0,r.stderr[:8192]);self.assertLessEqual(len(r.stdout),8*1024*1024);self.assertLessEqual(len(r.stderr),2*1024*1024);return r.stdout
 def worker(self,command,tar=None):
  self.assertRegex(IMAGE,r'^sha256:[0-9a-f]{64}$')
  argv=['container','create','--pull=never','--network=none','--user=0:0','--cap-drop=ALL','--security-opt=no-new-privileges=true','--ipc=none','--restart=no','--memory=2g','--memory-swap=2g','--cpus=2','--pids-limit=128','--ulimit=nofile=4096:4096','--ulimit=core=0:0']
  for cap in ['CHOWN','DAC_OVERRIDE','FOWNER','SETGID','SETUID','KILL']:argv+=['--cap-add='+cap]
  argv+=command[:1]+[IMAGE]+command[1:]
  cid=self.command(*argv).decode().strip();self.assertRegex(cid,r'^[a-f0-9]{64}$')
  try:
   inspected,=json.loads(self.command('container','inspect',cid));self.assertEqual(inspected['Image'],IMAGE);self.assertFalse(inspected['Mounts']);self.assertFalse(inspected['HostConfig']['Privileged']);self.assertEqual(inspected['HostConfig']['NetworkMode'],'none')
   if tar:self.command('container','cp','-',cid+':/',input=tar)
   output=self.command('container','start','--attach',cid,timeout=210)
   inspected,=json.loads(self.command('container','inspect',cid));self.assertEqual(inspected['State']['ExitCode'],0);self.assertFalse(inspected['State']['OOMKilled'])
   with tempfile.TemporaryDirectory() as temp:
    if tar:
     self.command('container','cp',cid+':/grade',temp+'/grade');root=Path(temp)/'grade';result=json.loads((root/'results/results.json').read_text())
     self.assertEqual(result['classification'],'success');self.assertEqual(result['score'],1)
     self.assertEqual(output,b'')
     if result.get('buildEvidence',{}).get('status')=='success':
      proof=result['buildEvidence'];artifact=root/proof['artifact']['path'];self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(),proof['artifact']['sha256'])
      with zipfile.ZipFile(artifact) as jar:self.assertIn('Main-Class: Student',jar.read('META-INF/MANIFEST.MF').decode().splitlines());self.assertNotIn('AnswerTest.class',jar.namelist())
     return result
    return json.loads(output)
  finally:
   self.command('container','rm','--force',cid)
   absence=subprocess.run(['docker','container','inspect',cid],capture_output=True,timeout=15);self.assertEqual(absence.returncode,1);self.assertEqual(absence.stdout,b'[]\n')
 def test_fresh_inventory_privacy_native_jar_and_legacy(self):
  code=r'''
import hashlib,importlib.util,json,os,stat,subprocess
from pathlib import Path
root=Path('/platform');spec=importlib.util.spec_from_file_location('grader',root/'images/java25-grader/grade.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
roles=g._role_records();g._build_tree_state(roles);g._hardened_tool_state();g._verify_landlock_helper()
lock=json.loads((root/'runtime/gradle-jar-v1/toolchain-lock.json').read_text())
for kind in ('jdk','gradle'):
 home=Path(lock[kind]['home']);observed={}
 for p in home.rglob('*'):
  s=p.lstat();assert s.st_uid==0 and s.st_gid==(roles['nativebuild']['gid'] if kind=='jdk' else 0) and not s.st_mode&0o022
  if p.is_dir():continue
  assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
  observed[p.relative_to(home).as_posix()]={'bytes':s.st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':oct(stat.S_IMODE(s.st_mode))}
 assert observed==lock[kind]['files']
normalizer_spec=importlib.util.spec_from_file_location('native_jdk_preparation',root/'tools/prepare_native_jdk.py');n=importlib.util.module_from_spec(normalizer_spec);import sys;sys.modules[normalizer_spec.name]=n;normalizer_spec.loader.exec_module(n)
receipt=json.loads(Path('/operator/normalization-receipt.json').read_text());assert receipt['actualCopyCreated'] and len(receipt['normalizedFiles'])==316
assert n._portable(n._snapshot(n.SOURCE_HOME,n._Policy()))==n._portable(receipt['sourceAfter'])==n._portable(receipt['sourceBefore'])
assert len(lock['jdk']['files'])==319 and len(lock['gradle']['files'])==716
assert not Path('/toolchain/gradle-9.8.0-bin.zip').exists() and not Path('/operator/components').exists()
assert all(stat.S_IMODE(p.stat().st_mode)==0o700 for p in [root,Path('/operator'),Path('/javagrader')])
baked=json.loads((root/'runtime-profiles.json').read_text());assert len(baked['profiles'])==3 and all('image' not in p for p in baked['profiles'].values())
# Root supervisor checks actual child caps/NNP/network in the isolated own namespace.
child=r"""
import ctypes,errno,json,os,socket
class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
libc=ctypes.CDLL(None,use_errno=True);header=Header(0x20080522,0);data=(Data*2)();assert libc.capget(ctypes.byref(header),data)==0
assert all(x.effective==x.permitted==x.inheritable==0 for x in data) and libc.prctl(39,0,0,0,0)==1
for path in ['/proc/self/maps','/platform/runtime-profiles.json','/dev/zero','/dev/urandom']:
 try:fd=os.open(path,os.O_RDONLY);os.close(fd);raise AssertionError('Forbidden read allowed')
 except PermissionError:pass
sock=socket.socket();sock.settimeout(1)
try:sock.connect(('198.51.100.1',9));raise AssertionError('Network connected')
except OSError:pass
finally:sock.close()
print('PASS')
"""
assert [p.name for p in Path('/sys/class/net').iterdir()]==['lo']
for role in ('nativebuild','sbuser'):
 r=subprocess.run(['/usr/sbin/runuser','-u',role,'--','/usr/local/bin/landlock_sandbox','python3','-I','-B','-c',child],cwd='/tmp',capture_output=True,timeout=10);assert r.returncode==0,r.stderr
# Independent UNIX read/copy/exec denial, not inferred from a failed JVM flag.
for p in ['/opt/native-jdk/bin/java','/opt/native-jdk/lib/libmanagement.so','/opt/native-jdk/lib/libmanagement_agent.so','/opt/native-jdk/lib/libmanagement_ext.so']:
 r=subprocess.run(['/usr/sbin/runuser','-u','sbuser','--','/bin/sh','-c','test ! -r "$1" && test ! -x "$1"','sh',p],capture_output=True,timeout=5);assert r.returncode==0
print(json.dumps({'completeJDK':319,'gradle':716,'roles':roles,'privacy':True}))
'''
  # This root canary does not run student bytes and does not broaden Landlock.
  proof=self.worker(['--entrypoint=python3','-I','-B','-c',code]);self.assertTrue(proof['privacy'])
  for native in [True,False]:
   cfg={'schemaVersion':1,'sourceFiles':['Student.java'],'testFiles':['AnswerTest.java'],'mode':'implementation','runtime':'java25-gradle-junit-v1' if native else 'java25-junit-v1','java':{'release':25,'encoding':'UTF-8','compiler-options':['-proc:none','-Xmaxerrs','5']},'limits':{'outer-seconds':210,'compile-seconds':15,'run-seconds':10,'max-output-bytes':65536,'networking':False},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
   if native:cfg['javaBuild']={'kind':'gradle-jar-v1','artifact':'student.jar','mainClass':'Student'}
   files={'student/Student.java':b'public class Student {public static int answer(){return 42;} public static void main(String[] a){System.out.println(answer());}}','tests/AnswerTest.java':b'import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest {@Test void value(){assertEquals(42,Student.answer());}}','tests/grading-job.json':json.dumps(cfg).encode()}
   stream=io.BytesIO()
   with tarfile.open(fileobj=stream,mode='w') as archive:
    for folder in ('grade','grade/student','grade/tests'):
     entry=tarfile.TarInfo(folder);entry.type=tarfile.DIRTYPE;entry.mode=0o755;archive.addfile(entry)
    for name,value in files.items():
     entry=tarfile.TarInfo('grade/'+name);entry.mode=0o644;entry.size=len(value);archive.addfile(entry,io.BytesIO(value))
   self.worker(['--workdir=/platform','--job-dir','/grade','--verification'],stream.getvalue())

if __name__=='__main__':unittest.main()
