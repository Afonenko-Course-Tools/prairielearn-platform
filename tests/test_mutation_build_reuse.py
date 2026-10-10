"""Real compilation regressions for job-scoped immutable runner reuse."""
import unittest
from pathlib import Path
from unittest.mock import patch
import test_grading_job as fixtures
class MutationBuildReuse(unittest.TestCase):
 setUp=fixtures.MutationJob.setUp
 setup_mutation=fixtures.MutationJob.setup_mutation
 run_job=fixtures.MutationJob.run_job
 def test_adapter_compiled_once_but_each_variant_keeps_distinct_typed_compilation(self):
  self.setup_mutation()
  with patch.object(fixtures.grader,'_run',wraps=fixtures.grader._run) as run:
   result=self.run_job()
  compiles=[c.args[0] for c in run.call_args_list if 'com.sun.tools.javac.Main' in c.args[0] and '-version' not in c.args[0]]
  adapters=[c for c in compiles if any(p.endswith('/PlatformJUnitAdapter.java') for p in c)]
  students=[c for c in compiles if any(p.endswith('/student/AnswerTest.java') for p in c)]
  trusted=[c for c in compiles if any('/tests/variants/' in p for p in c)]
  self.assertEqual(result['score'],1)
  self.assertEqual(len(adapters),1,'immutable official adapter must compile once per job')
  self.assertEqual(len(students),2,'submitted tests must compile against every variant API')
  self.assertEqual(len(trusted),2,'every trusted variant must compile independently')
  self.assertEqual(len({c[c.index('-d')+1] for c in students}),2)
  self.assertEqual(len({c[c.index('-d')+1] for c in trusted}),2)
 def test_variant_missing_api_still_produces_student_compilation_failure(self):
  self.setup_mutation()
  (self.job/'student/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest{@Test void right(){assertEquals(42,Student.answer());}}')
  (self.job/'tests/variants/wrong/Student.java').write_text('public class Student{}')
  result=self.run_job();self.assertEqual(result['classification'],'student-compilation-failure');self.assertFalse(result['gradable'])
 def test_new_job_does_not_reuse_compiled_adapter_from_previous_job(self):
  self.setup_mutation()
  with patch.object(fixtures.grader,'_run',wraps=fixtures.grader._run) as run:
   self.run_job();self.run_job()
  adapters=[c.args[0] for c in run.call_args_list if 'com.sun.tools.javac.Main' in c.args[0] and '-version' not in c.args[0] and any(p.endswith('/PlatformJUnitAdapter.java') for p in c.args[0])]
  self.assertEqual(len(adapters),2)
  self.assertEqual(len({c[c.index('-d')+1] for c in adapters}),2)

 def test_compiler_archive_is_job_private_and_all_variant_apis_still_compile(self):
  self.setup_mutation()
  with patch.object(fixtures.grader,'_run',wraps=fixtures.grader._run) as run:
   result=self.run_job()
  commands=[c.args[0] for c in run.call_args_list if 'com.sun.tools.javac.Main' in c.args[0] and '-version' not in c.args[0]]
  dumps=[p for c in commands for p in c if p.startswith('-XX:ArchiveClassesAtExit=')]
  loads=[p for c in commands for p in c if p.startswith('-XX:SharedArchiveFile=')]
  self.assertEqual(result['score'],1);self.assertEqual(len(dumps),1)
  self.assertEqual(len(loads),len(commands)-1)
  self.assertEqual({p.split('=',1)[1] for p in [*dumps,*loads]}, {dumps[0].split('=',1)[1]})
  self.assertFalse(Path(dumps[0].split('=',1)[1]).exists(),'archive removed at job completion')

 def test_every_variant_executes_in_fresh_jvm_with_bounded_tiered_startup(self):
  self.setup_mutation()
  with patch.object(fixtures.grader,'_run',wraps=fixtures.grader._run) as run:
   result=self.run_job()
  commands=[c.args[0] for c in run.call_args_list if 'PlatformJUnitAdapter' in c.args[0]]
  self.assertEqual(result['score'],1);self.assertEqual(len(commands),2)
  for command in commands:self.assertIn('-XX:TieredStopAtLevel=1',command)

 def test_missing_jdk_compiler_is_infrastructure_before_student_compilation(self):
  self.setup_mutation();original=fixtures.grader._run
  def run(command,*args,**kwargs):
   if 'com.sun.tools.javac.Main' in command and '-version' in command:return 1,'compiler unavailable',None
   return original(command,*args,**kwargs)
  with patch.object(fixtures.grader,'_run',side_effect=run):
   with self.assertRaisesRegex(fixtures.grader.GraderError,'JDK25 compiler'):self.run_job()
