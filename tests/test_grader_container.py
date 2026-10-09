"""Actual offline container execution at the declared PL CPU/memory limits."""
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_grading_job as fixtures
grader=fixtures.grader
@unittest.skipUnless(os.environ.get('PL_TEST_IMAGE'),'Set PL_TEST_IMAGE to an actual built image ID')
class ContainerParity(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 def test_same_payload_two_cold_jobs_match_host(self):
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg));host=grader.grade(self.job)
  values=[]
  for _ in range(2):
   p=subprocess.run(['docker','run','--rm','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount',f'type=bind,src={self.job},dst=/grade',os.environ['PL_TEST_IMAGE']],capture_output=True,text=True,timeout=30)
   self.assertEqual(p.returncode,0,p.stderr);r=json.loads((self.job/'results/results.json').read_text());values.append(r)
   self.assertEqual(r['score'],host['score']);self.assertEqual(r['counts'],host['counts']);self.assertEqual(r['rawResult'],host['rawResult'])
  for value in values:
   value.pop('durations');value.pop('toolchain')
  self.assertEqual(values[0],values[1])
 def test_outer_docker_failure_is_infrastructure(self):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'));from grading_job import GradingJob,run_job
  job=GradingJob(schemaVersion=1,scope='declared',qualifiedId='synthetic/exr-test',scenario='starter',sourceSnapshotHash='a'*64,inventoryHash='b'*64,runtime='java25-junit-v1',imageDigest='sha256:'+'0'*64,sources=[{'projectRelativePath':'Student.java','submissionRelativePath':'Student.java','sha256':'a'*64}],trustedTests=[{'projectRelativePath':'AnswerTest.java','submissionRelativePath':'AnswerTest.java','sha256':'b'*64}],grading=self.cfg,sourceHashes={},testsHashes={});job.root=self.job
  r=run_job(job,'container');self.assertEqual(r['classification'],'infrastructure-failure');self.assertNotIn('score',r)
 def test_official_sandbox_denies_proc_trusted_write_and_root_exec(self):
  self.cfg['limits']['run-seconds']=10
  (self.job/'student/Student.java').write_text('''public class Student {public static int answer() throws Exception {
   if(System.getProperty("sun.java.command","").contains("signature")) return 0;
   try { java.nio.file.Files.readString(java.nio.file.Path.of("/proc/self/maps"));return 0;} catch(java.nio.file.AccessDeniedException expected){}
   try { java.nio.file.Files.writeString(java.nio.file.Path.of("/grade/tests/injected"),"tampered");return 0;} catch(java.nio.file.AccessDeniedException expected){}
   try { java.nio.file.Files.writeString(java.nio.file.Path.of("/platform/runtime-profiles.json"),"tampered");return 0;} catch(java.nio.file.AccessDeniedException expected){}
   Process proc=new ProcessBuilder("/usr/bin/id","-u").start();String uid=new String(proc.getInputStream().readAllBytes()).trim();if(proc.waitFor()!=0 || uid.equals("0"))return 0;
   Process child=new ProcessBuilder("/bin/sh","-c","cat /proc/self/maps >/tmp/student-proc-copy").start();if(child.waitFor()==0)return 0;
   return 42;
  }}''')
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  p=subprocess.run(['docker','run','--rm','--network','none','--cpus','0.9','--memory','512m','--mount',f'type=bind,src={self.job},dst=/grade',os.environ['PL_TEST_IMAGE']],capture_output=True,text=True,timeout=30)
  self.assertEqual(p.returncode,0,p.stderr);r=json.loads((self.job/'results/results.json').read_text());self.assertEqual(r['score'],1,r);self.assertEqual(r['containment'],'official-landlock-sbuser');self.assertFalse((self.job/'tests/injected').exists())
 def test_outer_timeout_removes_actual_job_container(self):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'));from grading_job import GradingJob,run_job
  cfg=json.loads(json.dumps(self.cfg));cfg['limits']['outer-seconds']=1.0
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  job=GradingJob(schemaVersion=1,scope='declared',qualifiedId='synthetic/exr-timeout',scenario='starter',sourceSnapshotHash='a'*64,inventoryHash='b'*64,runtime='java25-junit-v1',imageDigest=os.environ['PL_TEST_IMAGE'],sources=[{'projectRelativePath':'Student.java','submissionRelativePath':'Student.java','sha256':'a'*64}],trustedTests=[{'projectRelativePath':'AnswerTest.java','submissionRelativePath':'AnswerTest.java','sha256':'b'*64}],grading=cfg,sourceHashes={},testsHashes={});job.root=self.job
  result=run_job(job,'container');self.assertEqual(result['classification'],'infrastructure-failure');self.assertNotIn('score',result)
  inspection=subprocess.run(['docker','inspect',job.containerName],capture_output=True)
  subprocess.run(['docker','rm','--force',job.containerName],capture_output=True)
  self.assertNotEqual(inspection.returncode,0)
