"""Private implementation mode and exact reported top origin; no lower-frame promotion."""
import json,unittest
from unittest.mock import patch
import test_grading_job as fixtures
from test_student_feedback import feedback

class DirectAssertionOrigin(unittest.TestCase):
 def fixture(self,student,tests=fixtures.TEST):
  f=fixtures.JUnitJob();f.setUp();self.addCleanup(f.doCleanups);(f.job/'student/Student.java').write_text(student);(f.job/'tests/AnswerTest.java').write_text(tests);return f
 def assert_kind(self,f,kind):
  r=f.run_job();native=feedback.student_result(r,f.cfg);self.assertEqual(native['feedback']['kind'],kind,r);self.assertNotIn('CLOSED_',json.dumps(native));self.assertEqual(set(r['counts']['failureKinds'].values()),{'runtime' if kind=='runtime' else 'wrong-answer'});return r
 def test_inner_and_secondary_compiled_students_are_runtime(self):
  for source in ['public class Student {static class Inner {static int value(){throw new AssertionError("CLOSED_INNER");}} public static int answer(){return Inner.value();}}','class Secondary {static int value(){throw new AssertionError("CLOSED_SECONDARY");}} public class Student {public static int answer(){return Secondary.value();}}']:
   with self.subTest(source=source):self.assert_kind(self.fixture(source),'runtime')
 def test_trusted_assertion_with_lower_student_frame_and_swallowed_error_are_behavior(self):
  source='public class Student {public static int answer(Runnable callback){callback.run();return 42;}}'
  tests='import org.junit.jupiter.api.Test;public class AnswerTest {@Test void callback()throws Exception{Class.forName("Student").getMethod("answer",Runnable.class).invoke(null,(Runnable)()->{throw new AssertionError("CLOSED_TRUSTED_CALLBACK");});}}'
  self.assert_kind(self.fixture(source,tests),'wrong-answer')
  self.assert_kind(self.fixture('public class Student {public static int answer(){try{throw new AssertionError("CLOSED_SWALLOWED");}catch(AssertionError ignored){return 0;}}}'),'wrong-answer')
  self.assert_kind(self.fixture('public class Student {public static int answer(){return 42;}}','import org.junit.jupiter.api.Test;public class AnswerTest {@Test void wrong(){throw new AssertionError("CLOSED_runtime_AssertionError");}}'),'wrong-answer')
 def test_missing_invalid_mode_or_origin_inventory_is_infrastructure(self):
  for changed in ['missing','unknown','boolean','root','inventory','class-name']:
   with self.subTest(changed=changed):
    f=self.fixture('public class Student {public static int answer(){throw new AssertionError("CLOSED_MODE");}}');original=json.dumps
    def private_params(value,*args,**kwargs):
     if isinstance(value,dict) and 'submission_mode' in value:
      value=dict(value)
      if changed=='missing':value.pop('submission_mode')
      elif changed=='unknown':value['submission_mode']='unknown'
      elif changed=='boolean':value['submission_mode']=True
      elif changed=='root':value['student_classes_root']=str(f.job)
      elif changed=='inventory':value['student_classes']=[]
      elif changed=='class-name':value['student_classes']=['Student$Invented']
     return original(value,*args,**kwargs)
    with patch.object(fixtures.grader.json,'dumps',side_effect=private_params):
     with self.assertRaises(fixtures.grader.GraderError):f.run_job()
 def test_internal_execution_mode_cannot_disagree_with_descriptor(self):
  f=self.fixture('public class Student {public static int answer(){return 42;}}');original=fixtures.grader._execute
  def mismatch(*args,**kwargs):kwargs['student_tests']=True;return original(*args,**kwargs)
  with patch.object(fixtures.grader,'_execute',side_effect=mismatch):
   with self.assertRaises(fixtures.grader.GraderError):f.run_job()
 def test_student_test_assertion_keeps_mutation_observation(self):
  f=fixtures.MutationJob();f.setUp();self.addCleanup(f.doCleanups);f.setup_mutation();r=f.run_job()
  self.assertEqual(r['score'],1);self.assertEqual(r['classification'],'success');self.assertEqual(set(r['variants']['wrong']['counts']['failureKinds'].values()),{'wrong-answer'})

 def test_forged_trace_and_foreign_loader_do_not_gain_reported_student_origin(self):
  ordinary='public class Student {public static int answer(){return 42;}}'
  forged='import org.junit.jupiter.api.Test;public class AnswerTest {@Test void forged(){AssertionError e=new AssertionError("CLOSED_FORGED_TRACE");e.setStackTrace(new StackTraceElement[]{new StackTraceElement("Student","answer","Student.java",1)});throw e;}}'
  self.assert_kind(self.fixture(ordinary,forged),'wrong-answer')
  source='public class Student {public static int answer(){throw new AssertionError("CLOSED_FOREIGN_LOADER");}}'
  tests='import org.junit.jupiter.api.Test;import java.net.*;public class AnswerTest {@Test void foreign()throws Exception{var url=Class.forName("Student",false,ClassLoader.getSystemClassLoader()).getProtectionDomain().getCodeSource().getLocation();try(var loader=new URLClassLoader("foreign-student-loader",new URL[]{url},ClassLoader.getPlatformClassLoader())){Class.forName("Student",true,loader).getMethod("answer").invoke(null);}}}'
  self.assert_kind(self.fixture(source,tests),'wrong-answer')

@unittest.skipUnless(__import__('os').environ.get('PL_TEST_IMAGE'),'Set exact local candidate image')
class DirectAssertionContainer(unittest.TestCase):
 def test_official_sandbox_keeps_private_origin_and_sanitizes_assertion(self):
  import os,subprocess
  f=fixtures.JUnitJob();f.setUp();self.addCleanup(f.doCleanups)
  (f.job/'student/Student.java').write_text('public class Student {static class Inner {static int value(){throw new AssertionError("CLOSED_CONTAINER_ASSERT");}}public static int answer(){return Inner.value();}}');(f.job/'tests/grading-job.json').write_text(json.dumps(f.cfg))
  command=['docker','run','--rm','--name','codex-common-b-direct-origin-01a1585d','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount','type=bind,src='+str(f.job)+',dst=/grade',os.environ['PL_TEST_IMAGE']]
  run=subprocess.run(command,capture_output=True,text=True,timeout=45);self.assertEqual(run.returncode,0,run.stderr);result=json.loads((f.job/'results/results.json').read_text());self.assertEqual(result['feedback']['kind'],'runtime');self.assertNotIn('CLOSED_',json.dumps(result)+run.stdout+run.stderr);self.assertNotIn('counts',result)
