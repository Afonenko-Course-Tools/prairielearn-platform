"""Actual canonical console helper; no stderr/message based classification."""
import json,os,shutil,subprocess,unittest
from pathlib import Path
import test_grading_job as fixtures
from test_student_feedback import feedback,ROOT

@unittest.skipUnless(os.environ.get('JAVA_CONSOLE_SUPPORT'),'Set JAVA_CONSOLE_SUPPORT to the canonical JavaProcess.java source')
class ConsoleFeedback(unittest.TestCase):
 def test_nested_process_failures_are_typed_and_nonzero_exit_is_allowed(self):
  for student,kind in [
   ('throw new IllegalStateException("CLOSED_CONSOLE_EXCEPTION");','runtime'),
   ('while(true){}','timeout'),
   ('while(true){System.out.print("CLOSED_OUTPUT_CANARY".repeat(1024));}','output-limit'),
   ('System.out.print("WRONG_PUBLIC");','wrong-answer'),
   ('System.out.print("PUBLIC_OK");System.exit(7);','success')]:
   with self.subTest(kind=kind):
    fixture=fixtures.JUnitJob();fixture.setUp()
    try:
     helper=fixture.job/'tests/coursesupport/JavaProcess.java';helper.parent.mkdir();shutil.copyfile(os.environ['JAVA_CONSOLE_SUPPORT'],helper)
     fixture.cfg['testFiles'].append('coursesupport/JavaProcess.java');fixture.cfg['limits']['outer-seconds']=45;fixture.cfg['limits']['run-seconds']=20
     (fixture.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+student+'}}')
     (fixture.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void console() throws Exception {var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");assertEquals("PUBLIC_OK",r.stdout());}}')
     result=fixture.run_job();native=feedback.student_result(result,fixture.cfg)
     self.assertEqual(native['feedback']['kind'],kind,result);self.assertNotIn('CLOSED_',json.dumps(native))
     expected_kind={'runtime':'runtime','timeout':'timeout','output-limit':'output-limit','wrong-answer':'wrong-answer'}.get(kind)
     if expected_kind:self.assertEqual(set(result['counts']['failureKinds'].values()),{expected_kind})
     import test_review_receipts as review
     bound=review.result();bound.update(result);bound['backend']='host';review.g.validate('check-result',bound)
     if kind=='success':self.assertEqual(result['score'],1)
    finally:fixture.doCleanups()

 def test_public_case_typed_failure_before_report_is_executed_not_unrun(self):
  for source,kind in [('throw new IllegalStateException("CLOSED_EARLY_RUNTIME");','runtime'),('while(true){}','timeout'),('while(true){System.out.print("CLOSED_EARLY_OUTPUT".repeat(1024));}','output-limit')]:
   with self.subTest(kind=kind):
    f,_=self.fixture();f.cfg['limits']['run-seconds']=20
    f.cfg['publicCases']=[{'id':'normal','name':'Обычный запуск возвращает результат','test':'AnswerTest#console','input':'','expected':'PUBLIC_OK'},{'id':'unrun','name':'Другой объявленный сценарий','test':'AnswerTest#unrun','input':'x','expected':'x'}]
    (f.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+source+'}}')
    (f.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;import java.util.Map;public class AnswerTest {@Test void console(TestReporter reporter)throws Exception{var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");reporter.publishEntry(Map.of("public-case","normal","actual",r.stdout()));assertEquals("PUBLIC_OK",r.stdout());}}')
    result=f.run_job();native=feedback.student_result(result,f.cfg)
    self.assertEqual(native['feedback']['kind'],kind)
    actual=native['feedback']['publicCases'][0];self.assertEqual(actual['status'],'failed');self.assertIsNotNone(actual['actual']);self.assertNotIn('CLOSED_',json.dumps(native))
    unrun=native['feedback']['publicCases'][1];self.assertEqual(unrun['status'],'not-run');self.assertIsNone(unrun['actual'])

 def fixture(self):
  f=fixtures.JUnitJob();f.setUp();self.addCleanup(f.doCleanups)
  helper=f.job/'tests/coursesupport/JavaProcess.java';helper.parent.mkdir();shutil.copyfile(os.environ['JAVA_CONSOLE_SUPPORT'],helper);f.cfg['testFiles'].append('coursesupport/JavaProcess.java')
  return f,helper
 def test_missing_companion_or_wrong_origin_is_infrastructure(self):
  from unittest.mock import patch
  for mode in ['missing-companion','origin']:
   with self.subTest(mode=mode):
    f,helper=self.fixture()
    if mode=='missing-companion':helper.write_text(helper.read_text().replace('StudentTimeout','MissingTimeout'))
    original=json.dumps
    def private_parameter(value,*args,**kwargs):
     if mode=='origin' and isinstance(value,dict) and 'trusted_console_support_root' in value:value={**value,'trusted_console_support_root':str(f.job)}
     return original(value,*args,**kwargs)
    with patch.object(fixtures.grader.json,'dumps',side_effect=private_parameter):
     with self.assertRaises(fixtures.grader.GraderError):f.run_job()
 def test_student_owner_or_inner_binary_collision_cannot_be_trusted(self):
  f,helper=self.fixture();student=f.job/'student/coursesupport/JavaProcess.java';student.parent.mkdir();shutil.copyfile(helper,student);f.cfg['sourceFiles'].append('coursesupport/JavaProcess.java')
  result=f.run_job();self.assertEqual(result['classification'],'unsafe-submission');self.assertNotIn('counts',result)
 def test_similar_assertion_name_or_text_is_not_typed_failure(self):
  f,_=self.fixture();(f.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;public class AnswerTest {static final class StudentTimeout extends AssertionError {} @Test void wrong(){throw new StudentTimeout();}}')
  result=f.run_job();self.assertEqual(result['classification'],'behavior-failure');self.assertEqual(set(result['counts']['failureKinds'].values()),{'wrong-answer'})
 def test_adapter_binding_does_not_initialize_common_and_other_loader_has_no_privilege(self):
  import tempfile
  f,helper=self.fixture()
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);trusted=root/'trusted';trusted.mkdir();source=root/'source/coursesupport/JavaProcess.java';source.parent.mkdir(parents=True)
   source.write_text(helper.read_text().replace('public final class JavaProcess {','public final class JavaProcess {static {System.setProperty("console.initialized","yes");}'))
   bundle=ROOT/'runtime/java25-junit-v1';runtime=fixtures.grader._JobRuntime(root,bundle);runtime.ensure_adapter(f.job,f.cfg['limits'],{},{});
   command=['javac','--release','25','-encoding','UTF-8','-d',str(trusted),str(source)];run=subprocess.run(command,capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
   probe=root/'BindingProbe.java';probe.write_text('import java.nio.file.*;import java.net.*;import java.util.*;public class BindingProbe {public static void main(String[] args)throws Exception {Class<?> adapter=Class.forName("PlatformJUnitAdapter");Object listener=adapter.getConstructor().newInstance();var bind=adapter.getDeclaredMethod("bindConsoleSupport",Object.class);bind.setAccessible(true);bind.invoke(listener,args[0]);if(System.getProperty("console.initialized")!=null)throw new AssertionError("binding initialized owner");var field=adapter.getDeclaredField("consoleFailures");field.setAccessible(true);Map<?,?> types=(Map<?,?>)field.get(listener);try(var foreign=new URLClassLoader(new URL[]{Path.of(args[0]).toUri().toURL()},null)){Class<?> spoof=Class.forName("coursesupport.JavaProcess$StudentTimeout",false,foreign);if(types.containsKey(spoof))throw new AssertionError("foreign loader gained typed privilege");}System.out.print("BOUND_WITHOUT_INITIALIZATION");}}')
   cp=os.pathsep.join([str(runtime.adapter),runtime.libs,str(trusted)]);run=subprocess.run(['javac','--release','25','-cp',cp,'-d',str(trusted),str(probe)],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
   run=subprocess.run(['java','-cp',cp,'BindingProbe',str(trusted)],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout,'BOUND_WITHOUT_INITIALIZATION')

 def test_student_descriptor_cannot_supply_trusted_origin_marker(self):
  f,_=self.fixture();f.cfg['trusted_console_support_root']=str(f.job)
  with self.assertRaises(fixtures.grader.GraderError):f.run_job()

@unittest.skipUnless(os.environ.get('PL_TEST_IMAGE') and os.environ.get('JAVA_CONSOLE_SUPPORT'),'Set exact candidate image and canonical console source')
class ConsoleContainerFeedback(unittest.TestCase):
 fixture=ConsoleFeedback.fixture
 def test_official_nested_process_runtime_and_legal_exit7(self):
  for source,kind in [('throw new IllegalStateException("CLOSED_NESTED_CONTAINER");','runtime'),('System.out.print("PUBLIC_OK");System.exit(7);','success')]:
   with self.subTest(kind=kind):
    f,_=self.fixture();f.cfg['publicCases']=[{'id':'normal','name':'Обычный запуск возвращает результат','test':'AnswerTest#console','input':'','expected':'PUBLIC_OK'}];(f.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+source+'}}');(f.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void console(org.junit.jupiter.api.TestReporter reporter)throws Exception{var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");reporter.publishEntry(java.util.Map.of("public-case","normal","actual",r.stdout()));assertEquals("PUBLIC_OK",r.stdout());}}');f.cfg['limits']['run-seconds']=15;(f.job/'tests/grading-job.json').write_text(json.dumps(f.cfg))
    run=subprocess.run(['docker','run','--rm','--name','codex-common-b-nested-origin-01a1585d','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount','type=bind,src='+str(f.job)+',dst=/grade',os.environ['PL_TEST_IMAGE']],capture_output=True,text=True,timeout=45)
    self.assertEqual(run.returncode,0,run.stderr);result=json.loads((f.job/'results/results.json').read_text());self.assertEqual(result['feedback']['kind'],kind);self.assertNotIn('CLOSED_',json.dumps(result)+run.stdout+run.stderr);case=result['feedback']['publicCases'][0];self.assertEqual(case['status'],'failed' if kind=='runtime' else 'passed');self.assertIsNotNone(case['actual'])
