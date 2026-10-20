"""Student boundary rejects private canaries, including failed runner reports."""
import importlib.util,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('student_feedback',ROOT/'runtime/student_feedback.py')
feedback=importlib.util.module_from_spec(spec);spec.loader.exec_module(feedback)
class StudentFeedback(unittest.TestCase):
 def test_private_default_and_error_classes(self):
  kinds={'student-compilation-failure':'compile','student-runtime-failure':'runtime','student-timeout':'timeout','behavior-failure':'wrong-answer','infrastructure-failure':'infrastructure'}
  for classification,kind in kinds.items():
   with self.subTest(classification=classification):
    result={'classification':classification,'score':0,'gradable':True,'message':'CLOSED_EXPECTED','output':'CLOSED_INPUT','tests':[{'name':'CLOSED_TEST','message':'CLOSED_TRACE'}],'rawResult':{'output':'CLOSED_SOURCE'},'diagnostics':['CLOSED_PATH'],'publicCaseObservations':[{'id':'secret','actual':'CLOSED_ACTUAL'}]}
    value=feedback.student_result(result,{})
    text=json.dumps(value,ensure_ascii=False)
    self.assertNotIn('CLOSED_',text);self.assertEqual(value['feedback']['kind'],kind)
    for name in ['reason','observed','whatCheck']:self.assertTrue(value['feedback'][name])
    self.assertNotEqual(value['feedback']['reason'],value['feedback']['observed'])
 def test_only_explicit_bound_public_cases_have_values(self):
  config={'publicCases':[{'id':'normal','name':'Обычный результат операции','test':'Demo#normal','action':'Вызвать sum(2, 3)','expected':'5'},{'id':'boundary','name':'Граничный случай операции','test':'Demo#boundary','input':'0','expected':'0'}]}
  result={'classification':'behavior-failure','score':0,'publicCaseObservations':[{'id':'normal','name':'Обычный результат операции','test':'Demo#normal','actual':'4','status':'failed'},{'id':'boundary','name':'Граничный случай операции','test':'Demo#boundary','actual':'0','status':'passed'},{'id':'normal','name':'Обычный результат операции','test':'Closed#private','actual':'CLOSED_CANARY','status':'failed'},{'id':'closed','test':'Closed#private','actual':'CLOSED_CANARY','status':'failed'}]}
  value=feedback.student_result(result,config);cases=value['feedback']['publicCases'];self.assertEqual(len(cases),2);self.assertEqual(cases[0]['actual'],'4');self.assertEqual(cases[0]['expected'],'5');self.assertEqual(cases[1]['status'],'passed');self.assertNotIn('CLOSED_',json.dumps(value));self.assertIn('Ожидается: 5',value['tests'][0]['description']);self.assertIn('Получено: 4',value['tests'][0]['description'])
 def test_input_only_success_explains_each_public_requirement_without_private_canary(self):
  descriptor={'publicCases':[{'id':'boundary','name':'Пустой ввод даёт пустой результат','test':'Demo#boundary','input':'','expected':''}]}
  value=feedback.student_result({'classification':'success','score':1,'output':'CLOSED_CANARY','publicCaseObservations':[{'id':'boundary','name':'Граничный случай операции','test':'Demo#boundary','actual':'','status':'passed'}]},descriptor)
  self.assertEqual(value['tests'][0]['name'],'Пустой ввод даёт пустой результат');self.assertIn('Что проверяется: Пустой ввод даёт пустой результат',value['tests'][0]['description']);self.assertEqual(value['feedback']['publicCases'][0]['name'],descriptor['publicCases'][0]['name']);self.assertNotIn('CLOSED_',json.dumps(value))
 def test_unobserved_public_case_does_not_invent_actual(self):
  value=feedback.student_result({'classification':'student-compilation-failure'},{'publicCases':[{'id':'normal','name':'Обычный результат операции','test':'Demo#normal','input':'2','expected':'5'}]})
  case=value['feedback']['publicCases'][0];self.assertEqual(case['status'],'not-run');self.assertIsNone(case['actual'])
 def test_infrastructure_is_not_wrong_answer(self):
  value=feedback.student_result({'classification':'infrastructure-failure','score':0,'gradable':True,'message':'CLOSED_SECRET'},{});self.assertTrue(value['grading_error']);self.assertFalse(value['gradable']);self.assertNotIn('score',value)

class ActualNativeFeedback(unittest.TestCase):
 def test_public_reporting_entries_and_private_canary(self):
  import test_grading_job as fixtures,subprocess,os
  fixture=fixtures.JUnitJob();fixture.setUp();self.addCleanup(fixture.doCleanups)
  fixture.cfg['publicCases']=[{'id':'normal','name':'Обычный результат операции','test':'AnswerTest#normal','input':'2, 3','expected':'5'},{'id':'boundary','name':'Граничный случай операции','test':'AnswerTest#boundary','input':'0, 0','expected':'0'}]
  (fixture.job/'student/Student.java').write_text('public class Student {public static int sum(int a,int b){return a+b;}}')
  (fixture.job/'tests/AnswerTest.java').write_text('''import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; import java.util.Map;
public class AnswerTest {
 @Test void normal(TestReporter reporter){int actual=Student.sum(2,3);reporter.publishEntry(Map.of("public-case","normal","actual",String.valueOf(actual)));assertEquals(5,actual);}
 @Test void boundary(TestReporter reporter){int actual=Student.sum(0,0);reporter.publishEntry(Map.of("public-case","boundary","actual",String.valueOf(actual)));assertEquals(0,actual);}
 @Test void closed(){System.out.print("CLOSED_INPUT_CANARY");assertEquals("CLOSED_EXPECTED_CANARY","CLOSED_ACTUAL_CANARY","CLOSED_TRACE_CANARY");}
}''')
  (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
  run=subprocess.run(['python3',str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(fixture.job)],text=True,capture_output=True,env=os.environ)
  self.assertEqual(run.returncode,0,run.stderr);result=json.loads((fixture.job/'results/results.json').read_text());self.assertNotIn('CLOSED_',json.dumps(result)+run.stdout+run.stderr)
  self.assertEqual(result['classification'],'behavior-failure');self.assertEqual(result['score'],2/3)
  self.assertEqual([(c['actual'],c['status']) for c in result['feedback']['publicCases']],[('5','passed'),('0','passed')])
 def test_student_exception_remains_runtime_without_message_leak(self):
  import test_grading_job as fixtures,subprocess,os
  fixture=fixtures.JUnitJob();fixture.setUp();self.addCleanup(fixture.doCleanups)
  (fixture.job/'student/Student.java').write_text('public class Student {public static int answer(){throw new IllegalStateException("CLOSED_RUNTIME_CANARY");}}')
  (fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
  run=subprocess.run(['python3',str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(fixture.job)],text=True,capture_output=True,env=os.environ)
  self.assertEqual(run.returncode,0,run.stderr);result=json.loads((fixture.job/'results/results.json').read_text());self.assertEqual(result['feedback']['kind'],'runtime');self.assertNotIn('CLOSED_',json.dumps(result)+run.stdout+run.stderr)

class ActualFailureBoundary(unittest.TestCase):
 def test_compile_timeout_and_infrastructure_cli_hide_canaries(self):
  import test_grading_job as fixtures,subprocess,os
  for kind,student,tests,exit_code in [
   ('compile','public class Student { CLOSED_COMPILER_CANARY }',fixtures.TEST,0),
   ('timeout','public class Student {public static int answer(){System.out.print("CLOSED_TIMEOUT_CANARY");while(true){}}}',fixtures.TEST,0),
   ('infrastructure','public class Student {public static int answer(){return 42;}}','CLOSED_INFRASTRUCTURE_CANARY',2),
   ('infrastructure','public class Student {public static int answer(){return 42;}}','import org.junit.jupiter.api.Test; public class AnswerTest { @Test void broken(){throw new NullPointerException("CLOSED_TRUSTED_SETUP_CANARY");}}',2)]:
   with self.subTest(kind=kind):
    fixture=fixtures.JUnitJob();fixture.setUp()
    try:
     (fixture.job/'student/Student.java').write_text(student);(fixture.job/'tests/AnswerTest.java').write_text(tests);(fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
     run=subprocess.run(['python3',str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(fixture.job)],text=True,capture_output=True,env=os.environ)
     self.assertEqual(run.returncode,exit_code,run.stderr);result=json.loads((fixture.job/'results/results.json').read_text());self.assertEqual(result['feedback']['kind'],kind);self.assertNotIn('CLOSED_',json.dumps(result)+run.stdout+run.stderr)
    finally:fixture.doCleanups()
 def test_only_operator_cli_enables_raw_verification(self):
  import test_grading_job as fixtures,subprocess,os
  fixture=fixtures.JUnitJob();fixture.setUp()
  try:
   (fixture.job/'student/Student.java').write_text('public class Student {public static int answer(){System.out.print("CLOSED_OPERATOR_CANARY");return 41;}}')
   config=fixture.job/'tests/grading-job.json';config.write_text(json.dumps(fixture.cfg))
   command=['python3',str(ROOT/'images/java25-grader/grade.py'),'--job-dir',str(fixture.job)]
   def execute(extra=[]):
    run=subprocess.run(command+extra,text=True,capture_output=True,env=os.environ);return run,json.loads((fixture.job/'results/results.json').read_text())
   run,native=execute();self.assertEqual(run.returncode,0);self.assertNotIn('CLOSED_',json.dumps(native)+run.stderr);self.assertNotIn('rawResult',native)
   run,private=execute(['--verification']);self.assertEqual(run.returncode,0);self.assertIn('CLOSED_OPERATOR_CANARY',json.dumps(private));self.assertIn('executionEvidence',private)
   config.write_text(json.dumps(dict(fixture.cfg,verification=True)));run,native=execute();self.assertEqual(run.returncode,2);self.assertNotIn('rawResult',native);self.assertNotIn('CLOSED_',json.dumps(native)+run.stderr)
   (fixture.job/'student/Student.java').rename(fixture.job/'student/--verification.java');fixture.cfg['sourceFiles']=['--verification.java'];config.write_text(json.dumps(fixture.cfg));run,native=execute();self.assertNotIn('rawResult',native);self.assertNotIn('CLOSED_',json.dumps(native)+run.stderr)
  finally:fixture.doCleanups()
 def test_internal_runtime_result_retains_private_verification_schema(self):
  import test_grading_job as fixtures,test_review_receipts as receipts
  fixture=fixtures.JUnitJob();fixture.setUp()
  try:
   (fixture.job/'student/Student.java').write_text('public class Student {public static int answer(){throw new IllegalArgumentException("PRIVATE");}}')
   actual=fixture.run_job();result=receipts.result();result['backend']='host';result.update(actual);receipts.g.validate('check-result',result)
  finally:fixture.doCleanups()

class ActualFishFeedback(unittest.TestCase):
 def test_public_observation_and_runtime_class(self):
  import tempfile
  spec=importlib.util.spec_from_file_location('feedback_fish',ROOT/'images/fish-git-grader/grade.py');grader=importlib.util.module_from_spec(spec);spec.loader.exec_module(grader)
  with tempfile.TemporaryDirectory() as tmp:
   job=Path(tmp);(job/'student').mkdir();(job/'tests').mkdir()
   cfg={'schemaVersion':1,'runtime':'fish-git-v1','mode':'implementation','sourceFiles':['answer.fish'],'testFiles':['checks.py'],'limits':{'outer-seconds':30,'run-seconds':1,'compile-seconds':5,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False},'publicCases':[{'id':'normal','name':'Обычный результат операции','test':'0: copy','input':'A','expected':'A'},{'id':'boundary','name':'Граничный случай операции','test':'1: copy','input':'','expected':''}]}
   (job/'tests/grading-job.json').write_text(json.dumps(cfg));(job/'tests/checks.py').write_text("def cases(tests):\n return [{'input.txt':'A'},{'input.txt':''},{'input.txt':'CLOSED_FISH_CANARY'}]\ndef check(root,inputs):\n actual=(root/'out.txt').read_text()\n return [('copy',actual==inputs['input.txt'],actual)]\n")
   source=job/'student/answer.fish';source.write_text('cat input.txt > out.txt\n')
   value=feedback.student_result(grader.grade(job),cfg);self.assertNotIn('CLOSED_',json.dumps(value));self.assertEqual([c['actual'] for c in value['feedback']['publicCases']],['A',''])
   source.write_text('echo CLOSED_FISH_RUNTIME >&2\nexit 3\n');value=feedback.student_result(grader.grade(job),cfg);self.assertEqual(value['feedback']['kind'],'runtime');self.assertNotIn('CLOSED_',json.dumps(value))

@unittest.skipUnless(__import__('os').environ.get('PL_TEST_IMAGE'),'Set PL_TEST_IMAGE to the exact local candidate')
class NativeContainerFeedback(unittest.TestCase):
 def test_same_image_native_default_and_private_operator_boundary(self):
  import test_grading_job as fixtures,subprocess,os
  fixture=fixtures.JUnitJob();fixture.setUp()
  try:
   (fixture.job/'student/Student.java').write_text('public class Student {public static int answer(){System.out.print("CLOSED_CONTAINER_CANARY");return 41;}}');(fixture.job/'tests/grading-job.json').write_text(json.dumps(fixture.cfg))
   command=['docker','run','--rm','--name','codex-common-b-feedback-01a1585d','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount','type=bind,src='+str(fixture.job)+',dst=/grade',os.environ['PL_TEST_IMAGE']]
   for args,private in [([],False),(['--verification'],True)]:
    run=subprocess.run(command+args,capture_output=True,text=True,timeout=60);self.assertEqual(run.returncode,0,run.stderr);result=json.loads((fixture.job/'results/results.json').read_text())
    if private:
     import test_review_receipts as receipts
     self.assertEqual(result['executionEvidence'],receipts.g.runtime_evidence('java25-junit-v1'));self.assertIn('CLOSED_CONTAINER_CANARY',json.dumps(result));self.assertIn('executionEvidence',result);self.assertEqual(result['containment'],'official-landlock-sbuser')
    else:self.assertNotIn('CLOSED_',json.dumps(result)+run.stderr);self.assertNotIn('rawResult',result);self.assertEqual(result['feedback']['kind'],'wrong-answer')
  finally:fixture.doCleanups()

@unittest.skipUnless(__import__('os').environ.get('PL_FISH_TEST_IMAGE'),'Set PL_FISH_TEST_IMAGE to exact local candidate')
class NativeFishContainerFeedback(unittest.TestCase):
 def test_same_fish_image_native_and_private_boundary(self):
  import tempfile,subprocess,os
  with tempfile.TemporaryDirectory() as tmp:
   job=Path(tmp);(job/'student').mkdir();(job/'tests').mkdir()
   cfg={'schemaVersion':1,'runtime':'fish-git-v1','mode':'implementation','sourceFiles':['answer.fish'],'testFiles':['checks.py'],'limits':{'outer-seconds':30,'run-seconds':1,'compile-seconds':5,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False},'publicCases':[{'id':'normal','name':'Обычный результат операции','test':'0: copy','input':'A','expected':'A'},{'id':'boundary','name':'Граничный случай операции','test':'1: copy','input':'','expected':''}]}
   (job/'tests/grading-job.json').write_text(json.dumps(cfg));(job/'tests/checks.py').write_text("def cases(tests):\n return [{'input.txt':'A'},{'input.txt':''},{'input.txt':'CLOSED_FISH_INPUT'}]\ndef check(root,inputs):\n actual=(root/'out.txt').read_text()\n return [('copy',actual==inputs['input.txt'],actual)]\n");(job/'student/answer.fish').write_text('cat input.txt > out.txt\necho CLOSED_FISH_CONTAINER\n')
   command=['docker','run','--rm','--name','codex-common-b-fish-feedback-01a1585d','--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount','type=bind,src='+str(job)+',dst=/grade',os.environ['PL_FISH_TEST_IMAGE']]
   for args,private in [([],False),(['--verification'],True)]:
    run=subprocess.run(command+args,capture_output=True,text=True,timeout=60);self.assertEqual(run.returncode,0,run.stderr);result=json.loads((job/'results/results.json').read_text())
    if private:
     import test_review_receipts as receipts
     self.assertEqual(result['executionEvidence'],receipts.g.runtime_evidence('fish-git-v1'));self.assertIn('CLOSED_FISH_CONTAINER',json.dumps(result));self.assertIn('executionEvidence',result);self.assertEqual(result['containment'],'official-landlock-sbuser')
    else:self.assertNotIn('CLOSED_',json.dumps(result)+run.stderr);self.assertEqual([c['actual'] for c in result['feedback']['publicCases']],['A',''])

class DirectStudentAssertion(unittest.TestCase):
 def test_implementation_assertion_from_student_code_is_runtime(self):
  import test_grading_job as fixtures
  fixture=fixtures.JUnitJob();fixture.setUp()
  try:
   (fixture.job/'student/Student.java').write_text('public class Student {public static int answer(){throw new AssertionError("CLOSED_STUDENT_ASSERT_CANARY");}}')
   result=fixture.run_job();native=feedback.student_result(result,fixture.cfg)
   self.assertEqual(native['feedback']['kind'],'runtime');self.assertNotIn('CLOSED_',json.dumps(native))
  finally:fixture.doCleanups()
