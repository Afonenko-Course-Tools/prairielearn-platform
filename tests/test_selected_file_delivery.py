"""Выбранные bytes проходят в grader без физического дерева и собственных proof."""
import base64,copy,json,shutil,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
from gradle_unit_fixtures import registry

def row(name,data,target=None):
 return {'name':name,'target':target or 'student/'+name,'data':base64.b64encode(data).decode()}
def manifest():
 return {'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','projects':[{
  'exerciseId':'exr-answer','qualifiedId':'demo/exr-answer','source':'labs/answer.qmd','projectRoot':'projects/answer','bankMember':True,
  'check':{'profile':'junit','runtime':'java25-junit-v1','source-profile':'student','sourceProfile':{'mode':'implementation','root':'student','include':['*.java']},'references':[]},
  'sources':[row('Answer.java',b'public class Answer {}')],
  'trustedTests':[row('AnswerTest.java',b'PRIVATE_TEST','author/trusted/AnswerTest.java')],
  'verificationTests':[],'references':[],'contractFixtures':[],'readiness':{'ready':True,'missing':[]}}]}
class SelectedDelivery(unittest.TestCase):
 def setUp(self):
  self.m=manifest();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
 def prepare(self,scenario='starter'):
  job=g.prepare_job(self.m,Path(self.tmp.name),'demo/exr-answer',scenario,registry=registry());self.addCleanup(lambda:shutil.rmtree(job.root));return job
 def test_actual_selected_bytes_need_no_origin_tree_or_fingerprint(self):
  job=self.prepare();self.assertEqual((job.root/'student/Answer.java').read_bytes(),b'public class Answer {}');self.assertEqual((job.root/'tests/AnswerTest.java').read_bytes(),b'PRIVATE_TEST')
  self.assertEqual(list((job.root/'student').iterdir()),[job.root/'student/Answer.java'])
  self.assertFalse({'sourceSnapshotHash','inventoryHash','sourceHashes','testsHashes','nativeSelectionScopeHash','deliveryHash'}&job.keys())
 def test_changed_selected_bytes_are_used_directly(self):
  self.m['projects'][0]['sources'][0]=row('Answer.java',b'CURRENT_BYTES');self.assertEqual((self.prepare().root/'student/Answer.java').read_bytes(),b'CURRENT_BYTES')
 def test_bad_paths_data_duplicates_and_limits_fail_before_scratch(self):
  original=copy.deepcopy(self.m)
  for rows in [[row('../escape',b'x')],[row('Answer.java',b'x'),row('Answer.java',b'y')],[row('A.java',b'x'),row('A.java/child',b'y')],[row('A.java',b'x',target='../secret')],[{'name':'A.java','target':'student/A.java','data':'!bad'}],[row('A.java',b'x'*(1048576+1))]]:
   with self.subTest(rows=[r['name'] for r in rows]):
    self.m=copy.deepcopy(original);self.m['projects'][0]['sources']=rows
    with self.assertRaises(g.JobError):self.prepare()
 def test_fixed_archive_additional_flag_survives_profile_translation(self):
  self.m['projects'][0]['check']['additional-java-sources']={'archive':'answer.zip','primary-required':True,'allow-additional':False,'max-files':128,'max-file-bytes':1048576,'max-total-bytes':4194304,'max-archive-bytes':2097152}
  job=self.prepare();self.assertIs(job['grading']['additionalJavaSources']['allowAdditional'],False)
  self.assertIs(json.loads((job.root/'tests/grading-job.json').read_text())['additionalJavaSources']['allowAdditional'],False)
 def test_missing_required_check_is_project_defect(self):
  self.m['projects'][0]['readiness']={'ready':False,'missing':['tests']}
  with self.assertRaises(g.ProjectDefect):self.prepare()
 def test_optional_reference_unavailable_is_explicit(self):
  p=self.m['projects'][0];p['check']['references']=[{'name':'correct','root':'author/correct','optional':True}];p['references']=[{'name':'correct','root':'author/correct','optional':True,'available':False,'group':'correct','targets':[],'sources':[]}]
  with self.assertRaisesRegex(g.JobError,'reference-unavailable:correct'):self.prepare('reference:correct')
 def test_named_reference_uses_its_selected_bytes(self):
  p=self.m['projects'][0];p['check']['references']=[{'name':'correct','root':'author/correct','optional':False}];p['references']=[{'name':'correct','root':'author/correct','optional':False,'available':True,'group':'correct','targets':['author/correct/Answer.java'],'sources':[row('Answer.java',b'REFERENCE','author/correct/Answer.java')]}]
  self.assertEqual((self.prepare('reference:correct').root/'student/Answer.java').read_bytes(),b'REFERENCE')
 def test_contract_scenario_uses_functional_fixture_targets(self):
  p=self.m['projects'][0];p['check']['contract-cases']='cases.json';p['contractCases']=row('cases.json',json.dumps({'schemaVersion':1,'cases':[{'id':'bad','sources':[{'fixture':'tests/fixtures/bad.java','submission':'Answer.java'}],'expected':{'student-compilation':'failure'}}]}).encode(),'author/cases.json');p['contractFixtures']=[row('Answer.java',b'BAD','tests/fixtures/bad.java')]
  scenarios=g.scenario_inventory(self.m,Path(self.tmp.name));self.assertEqual([x['scenario'] for x in scenarios],['contract:bad','starter']);self.assertEqual((self.prepare('contract:bad').root/'student/Answer.java').read_bytes(),b'BAD')
if __name__=='__main__':unittest.main()

class RealSelectedGrader(unittest.TestCase):
 setUp=SelectedDelivery.setUp
 prepare=SelectedDelivery.prepare
 def test_real_grader_preserves_success_student_and_tool_failure(self):
  import os
  os.environ['PATH']='/usr/lib/jvm/java-25-openjdk/bin:'+os.environ['PATH']
  p=self.m['projects'][0]
  p['sources']=[row('Answer.java',b'public class Answer {public static int value(){return 42;}}')]
  p['trustedTests']=[row('AnswerTest.java',b'import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest {@Test void value(){assertEquals(42,Answer.value());}}','author/trusted/AnswerTest.java')]
  result=g.run_job(self.prepare(),registry=registry());self.assertEqual(result['score'],1);self.assertEqual(result['classification'],'success');self.assertFalse({'sourceHashes','testsHashes','deliveryHash'}&result.keys())
  p['sources']=[row('Answer.java',b'not java')];result=g.run_job(self.prepare(),registry=registry());self.assertEqual(result['classification'],'student-compilation-failure');self.assertEqual(result['score'],0)
  p['sources']=[row('Answer.java',b'public class Answer {}')];p['trustedTests']=[row('AnswerTest.java',b'not java','author/trusted/AnswerTest.java')];result=g.run_job(self.prepare(),registry=registry());self.assertEqual(result['classification'],'infrastructure-failure');self.assertNotIn('score',result)
