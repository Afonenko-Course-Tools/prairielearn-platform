import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import test_grading_job as fixtures

class ProcessFileLimit(unittest.TestCase):
 def test_supervisor_caps_child_hard_limit_without_changing_parent(self):
  import resource
  before=resource.getrlimit(resource.RLIMIT_NOFILE)
  code,text,reason=fixtures.grader._run([sys.executable,'-c','import resource;print(resource.getrlimit(resource.RLIMIT_NOFILE)[1])'],Path.cwd(),5)
  self.assertEqual(code,0);self.assertIsNone(reason);self.assertLessEqual(int(text),4096)
  self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE),before)

@unittest.skipUnless(os.environ.get('PL_TEST_IMAGE'),'Set PL_TEST_IMAGE to an actual built image ID')
class NestedJvm(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 def test_six_fresh_scanner_jvms_keep_proc_denied_under_native_limits(self):
  self.cfg['limits']['run-seconds']=10
  (self.job/'student/Student.java').write_text('''public class Student {
 static final java.util.Scanner INPUT=new java.util.Scanner(System.in);
 public static void main(String[] args){System.out.println(INPUT.nextInt()+" "+args[0]);}
 public static int answer() throws Exception {
 try {java.nio.file.Files.readString(java.nio.file.Path.of("/proc/self/maps"));throw new AssertionError("proc readable");}catch(java.nio.file.AccessDeniedException expected){}
 for(int i=0;i<6;i++) {
 Process p=new ProcessBuilder(System.getProperty("java.home")+"/bin/java","-cp",System.getProperty("java.class.path"),"Student","Ли 🌟").start();
 p.getOutputStream().write("42\\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));p.getOutputStream().close();
 String text=new String(p.getInputStream().readAllBytes(),java.nio.charset.StandardCharsets.UTF_8).trim();
 if(p.waitFor()!=0 || !text.equals("42 Ли 🌟"))throw new AssertionError("child stdin/output "+text);
 }return 42;
 }}''')
  (self.job/'tests/grading-job.json').write_text(json.dumps(self.cfg))
  result=subprocess.run(['docker','run','--rm','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount',f'type=bind,src={self.job},dst=/grade',os.environ['PL_TEST_IMAGE'],'--verification'],capture_output=True,text=True,timeout=30)
  self.assertEqual(result.returncode,0,result.stderr)
  actual=json.loads((self.job/'results/results.json').read_text());self.assertEqual(actual['score'],1,actual);self.assertEqual(actual['containment'],'official-landlock-sbuser')
