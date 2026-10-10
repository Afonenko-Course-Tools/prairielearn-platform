"""The Platform result must reach the native external-grader feedback renderer."""
import json
import os
from pathlib import Path
import unittest
import test_grading_job as fixtures

class NativeFeedbackTests(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 run_job=fixtures.JUnitJob.run_job
 def result(self,name,source):
  (self.job/'student/Student.java').write_text(source)
  result=self.run_job()
  self.capture(name,result)
  return result
 def capture(self,name,result):
  if os.environ.get('PL_FEEDBACK_CAPTURE_DIR'):
   output=Path(os.environ['PL_FEEDBACK_CAPTURE_DIR']);output.mkdir(parents=True,exist_ok=True)
   (output/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 def test_missing_api_has_native_test_message(self):
  r=self.result('missing-api','public class Student {}')
  self.assertEqual(r['classification'],'behavior-failure');self.assertEqual(r['score'],0)
  self.assertEqual(r['counts']['failed'],1);self.assertEqual(r['counts']['executed'],1)
  self.assertEqual(len(r.get('tests',[])),1,'Native UI requires tests at the result root')
  self.assertIn('answer',r['tests'][0]['message']);self.assertEqual(r['tests'][0]['points'],0)
  self.assertEqual(r['tests'][0]['max_points'],1)
 def test_silent_timeout_has_native_message(self):
  r=self.result('timeout','public class Student {public static int answer(){while(true){}}}')
  self.assertEqual(r['classification'],'student-timeout');self.assertEqual(r['score'],0)
  self.assertTrue(r['timed_out']);self.assertFalse(r['output_limited'])
  self.assertIn('time',r.get('message','').lower(),'Native UI must explain an inner timeout')
  self.assertIn('3',r['message']);self.assertNotIn('tests',r)
 def test_output_overflow_has_native_message(self):
  r=self.result('overflow','public class Student {public static int answer(){while(true){System.out.print("x".repeat(8192));}}}')
  self.assertEqual(r['classification'],'student-output-overflow');self.assertEqual(r['score'],0)
  self.assertTrue(r['output_limited']);self.assertFalse(r['timed_out'])
  self.assertIn('output',r.get('message','').lower());self.assertIn('65536',r['message'])
  self.assertLessEqual(len(r['output'].encode()),65536)
 def test_mutation_success_explains_expected_rejections(self):
  fixtures.MutationJob.setup_mutation(self)
  r=self.run_job();self.capture('mutation-success',r)
  self.assertEqual(r['score'],1);self.assertEqual(r['classification'],'success')
  self.assertEqual(r['variants']['correct']['counts']['passed'],1)
  self.assertEqual(r['variants']['wrong']['counts']['failed'],1)
  self.assertIn('Correct implementations accepted: 1/1',r.get('message',''))
  self.assertIn('mutants rejected: 1/1',r['message']);self.assertNotIn('tests',r)
 def test_mutation_noop_explains_missing_rejections(self):
  fixtures.MutationJob.setup_mutation(self)
  (self.job/'student/AnswerTest.java').write_text('import org.junit.jupiter.api.Test; public class AnswerTest { @Test void noop(){} }')
  r=self.run_job();self.capture('mutation-noop',r)
  self.assertEqual(r['score'],0);self.assertEqual(r['classification'],'behavior-failure')
  self.assertEqual(r['variants']['wrong']['counts']['failed'],0)
  self.assertIn('Correct implementations accepted: 1/1',r.get('message',''))
  self.assertIn('mutants rejected: 0/1',r['message']);self.assertNotIn('tests',r)
 def test_mutation_disabled_reports_quality_failure(self):
  fixtures.MutationJob.setup_mutation(self)
  (self.job/'student/AnswerTest.java').write_text(fixtures.TEST.replace('@Test','@org.junit.jupiter.api.Disabled @Test'))
  r=self.run_job();self.capture('mutation-quality',r)
  self.assertEqual(r['classification'],'student-test-quality-failure');self.assertEqual(r['score'],0)
  self.assertIn('quality',r.get('message','').lower());self.assertNotIn(str(self.job),r['message'])
