"""Compiler rejection and runner limits preserve distinct private phase evidence."""
import json,unittest
from unittest.mock import patch
import jsonschema
import test_grading_job as fixtures
class BindingStages(unittest.TestCase):
 setUp=fixtures.JUnitJob.setUp
 run_job=fixtures.JUnitJob.run_job
 def test_real_trusted_rejection_retains_existing_raw_schema_and_native_privacy(self):
  (self.job/'tests/AnswerTest.java').write_text('class AnswerTest { CLOSED_BINDING_CANARY value; }')
  raw=self.run_job();self.assertEqual(raw['classification'],'infrastructure-failure');self.assertFalse(raw['gradable']);self.assertNotIn('score',raw)
  self.assertEqual((raw['studentCompilation'],raw['trustedCompilation'],raw['dependentExecution']),('success','failure','not-run'))
  self.assertIn('CLOSED_BINDING_CANARY',json.dumps(raw))
  schema=json.loads((fixtures.ROOT/'schemas/check-result.schema.json').read_text());jsonschema.Draft202012Validator({'$ref':'#/$defs/outcome','$defs':schema['$defs']}).validate(raw)
  import runpy
  native=runpy.run_path(str(fixtures.ROOT/'runtime/student_feedback.py'))['student_result'](raw,self.cfg)
  self.assertNotIn('CLOSED_BINDING_CANARY',json.dumps(native));self.assertEqual(native['classification'],'infrastructure-failure');self.assertNotIn('studentCompilation',native)
 def test_trusted_compiler_limit_remains_infrastructure_not_completed_binding(self):
  original=fixtures.grader._run
  def limit(command,*args,**kwargs):
   if any(str(x).endswith('/tests/AnswerTest.java') for x in command):return -1,'PRIVATE_LIMIT_CANARY','timeout'
   return original(command,*args,**kwargs)
  with patch.object(fixtures.grader,'_run',side_effect=limit),self.assertRaises(fixtures.grader.GraderError):self.run_job()
 def test_student_tests_trusted_failure_never_claims_student_success(self):
  self.cfg.update(mode='student-tests',runtime='java25-mutation-v1',sourceFiles=['AnswerTest.java'],testFiles=['variants/correct/Student.java','variants/wrong/Student.java'],variants={'correct':['correct'],'mutants':['wrong']},scoring={'mode':'all-pass'})
  (self.job/'student/Student.java').unlink();(self.job/'student/AnswerTest.java').write_text(fixtures.TEST)
  for name in ['correct','wrong']:
   p=self.job/f'tests/variants/{name}/Student.java';p.parent.mkdir(parents=True);p.write_text('not java')
  with self.assertRaises(fixtures.grader.GraderError):self.run_job()
