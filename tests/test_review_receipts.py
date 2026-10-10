"""Review regressions: omitted scenarios, image substitution, expected invalidity."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
IMAGE='registry.example/runtime@sha256:'+'a'*64

def result(scenario='starter',image=IMAGE):
 return {'schemaVersion':1,'scope':'delivery','backend':'container','qualifiedId':'demo/exr-a','scenario':scenario,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'deliveryHash':'c'*64,'runtime':'java25-junit-v1','imageDigest':image,'executionEvidence':g.runtime_evidence('java25-junit-v1'),'sourceHashes':{'S.java':'a'*64},'testsHashes':{'T.java':'b'*64},'gradable':True,'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','classification':'success','counts':{'discovered':1,'executed':1,'passed':1,'failed':0,'skipped':0,'aborted':0,'containerFailures':0,'outcomes':{'T#t':'successful'}},'score':1,'maxPoints':1,'rawResult':{'score':1,'points':1,'max_points':1,'output':'','message':'','gradable':True,'tests':[{'name':'t','description':'','points':1,'max_points':1,'output':'','message':''}]},'durations':{'execution':1},'diagnostics':{},'toolchain':'JDK25','containment':'official-landlock-sbuser','scoring':{'mode':'weighted'},'output':''}
class ReviewReceipts(unittest.TestCase):
 def test_starter_only_cannot_claim_complete_scenario_coverage(self):
  receipt=g.verify_results([result()],{})
  self.assertEqual(receipt.get('coverage'),'partial')
 def test_mixed_image_for_same_runtime_is_rejected(self):
  with self.assertRaises(g.JobError):g.verify_results([result(),result('reference:default','registry.example/runtime@sha256:'+'d'*64)],{})
 def test_negative_compilation_contract_matches_without_defect(self):
  r=result('contract:invalid')
  for k in ['counts','score','maxPoints','rawResult','durations','diagnostics','toolchain','containment','scoring']:r.pop(k)
  r.update(gradable=False,studentCompilation='failure',trustedCompilation='not-run',classification='student-compilation-failure',format_errors='invalid source')
  receipt=g.verify_results([r],{'contract:invalid':{'student-compilation':'failure','job':'complete','classification':'student-compilation-failure'}})
  self.assertEqual(receipt['exitCode'],0)
 def test_minimal_claimed_success_is_schema_invalid(self):
  r={k:result()[k] for k in ['schemaVersion','scope','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','runtime','infrastructure','classification']}
  with self.assertRaises(g.JobError):g.validate('check-result',r)
 def test_delivery_result_requires_delivery_hash(self):
  r=result();r.pop('deliveryHash')
  with self.assertRaises(g.JobError):g.validate('check-result',r)
 def test_success_cannot_contain_infrastructure_error(self):
  r=result();r['grading_error']=True
  with self.assertRaises(g.JobError):g.validate('check-result',r)
 def test_resolved_descriptor_requires_full_nested_options(self):
  cfg={'schemaVersion':1,'sourceFiles':['S.java'],'testFiles':['T.java'],'mode':'implementation','runtime':'java25-junit-v1','java':{},'limits':{},'scoring':{'mode':'weighted'},'discovery':{}}
  with self.assertRaises(g.JobError):g.validate('grading-descriptor',cfg)
 def test_complete_receipt_records_optional_reference_unavailability(self):
  required=[{'qualifiedId':'demo/exr-a','scenario':'reference:optional','optional':True},{'qualifiedId':'demo/exr-a','scenario':'starter','optional':False}]
  unavailable=[{'qualifiedId':'demo/exr-a','scenario':'reference:optional','status':'reference-unavailable'}]
  receipt=g.verify_results([result()],{},required,unavailable)
  self.assertEqual(receipt['coverage'],'complete');self.assertEqual(receipt['unavailableReferences'],unavailable)
 def test_receipt_with_contradictory_exit_code_is_schema_invalid(self):
  receipt=g.verify_results([result()],{});receipt['exitCode']=2
  with self.assertRaises(g.JobError):g.validate('verification-receipt',receipt)
 def test_nested_variant_outcome_cannot_omit_compilation_counts_and_raw_results(self):
  r=result();r.pop('counts');r.pop('rawResult');r['variants']={'correct':{'infrastructure':'complete','classification':'success'},'mutant':{'infrastructure':'complete','classification':'behavior-failure'}}
  with self.assertRaises(g.JobError):g.validate('check-result',r)
 def test_required_reference_cannot_be_marked_unavailable(self):
  required=[{'qualifiedId':'demo/exr-a','scenario':'reference:default','optional':False},{'qualifiedId':'demo/exr-a','scenario':'starter','optional':False}]
  with self.assertRaises(g.JobError):g.verify_results([result()],{},required,[{'qualifiedId':'demo/exr-a','scenario':'reference:default','status':'reference-unavailable'}])
 def test_single_question_cannot_switch_between_runtime_profiles(self):
  a=result();b=result('reference:default');b['runtime']='java25-mutation-v1'
  with self.assertRaises(g.JobError):g.verify_results([a,b],{})
 def test_scenario_inventory_includes_all_named_refs_and_hashed_contracts(self):
  import hashlib,tempfile
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);p=root/'tasks/project';p.mkdir(parents=True)
   cases={'schemaVersion':1,'cases':[{'id':'broken','sources':[{'fixture':'tests/fixtures/S.java','submission':'S.java'}],'expected':{'student-compilation':'failure'}}]}
   casefile=p/'cases.json';casefile.write_text(json.dumps(cases))
   manifest={'schemaVersion':1,'bookRoot':'tasks','projects':[{'qualifiedId':'demo/exr-a','projectRoot':'project','check':{'references':[{'name':'default','root':'reference'},{'name':'extra','root':'extra','optional':True}],'contract-cases':'cases.json'},'contractCasesHash':{'projectRelativePath':'cases.json','sha256':hashlib.sha256(casefile.read_bytes()).hexdigest()}}]}
   actual=g.scenario_inventory(manifest,root)
   self.assertEqual(actual,[{'qualifiedId':'demo/exr-a','scenario':'contract:broken','optional':False},{'qualifiedId':'demo/exr-a','scenario':'reference:default','optional':False},{'qualifiedId':'demo/exr-a','scenario':'reference:extra','optional':True},{'qualifiedId':'demo/exr-a','scenario':'starter','optional':False}])
   casefile.write_text('{}')
   with self.assertRaises(g.JobError):g.scenario_inventory(manifest,root)
 def test_executed_dependency_substitution_is_rejected(self):
  r=result();r['executionEvidence']['dependencyHashes']['runner/grade.py']='d'*64
  with self.assertRaises(g.JobError):g.verify_results([r],{})
 def test_defect_receipt_cannot_claim_all_expectations_matched(self):
  receipt=g.verify_results([result()],{});receipt.update(status='defect',exitCode=1)
  with self.assertRaises(g.JobError):g.validate('verification-receipt',receipt)
 def test_real_invalid_java_contract_matches_expected_compilation_failure(self):
  import test_grading_job as fixtures
  case=fixtures.JUnitJob();case.setUp()
  try:
   (case.job/'student/Student.java').write_text('invalid java syntax')
   (case.job/'tests/grading-job.json').write_text(json.dumps(case.cfg))
   job=g.GradingJob(schemaVersion=1,scope='declared',qualifiedId='demo/exr-a',scenario='contract:invalid',sourceSnapshotHash='a'*64,inventoryHash='b'*64,runtime='java25-junit-v1',imageDigest=None,sources=[{'projectRelativePath':'S.java','submissionRelativePath':'Student.java','sha256':'a'*64}],trustedTests=[{'projectRelativePath':'T.java','submissionRelativePath':'AnswerTest.java','sha256':'b'*64}],grading=case.cfg,sourceHashes={},testsHashes={});job.root=case.job
   actual=g.run_job(job,'host');self.assertEqual(actual['classification'],'student-compilation-failure')
   receipt=g.verify_results([actual],{'contract:invalid':{'student-compilation':'failure','job':'complete','classification':'student-compilation-failure'}})
   self.assertEqual(receipt['exitCode'],0)
  finally:case.doCleanups()
 def test_real_mutation_outcomes_validate_strict_nested_union(self):
  import test_grading_job as fixtures
  case=fixtures.MutationJob();case.setUp();case.setup_mutation()
  try:
   (case.job/'tests/grading-job.json').write_text(json.dumps(case.cfg))
   sources=[{'projectRelativePath':'AnswerTest.java','submissionRelativePath':'AnswerTest.java','sha256':'a'*64}]
   tests=[{'projectRelativePath':p,'submissionRelativePath':p,'sha256':'b'*64} for p in case.cfg['testFiles']]
   job=g.GradingJob(schemaVersion=1,scope='declared',qualifiedId='demo/exr-a',scenario='starter',sourceSnapshotHash='a'*64,inventoryHash='b'*64,runtime='java25-mutation-v1',imageDigest=None,sources=sources,trustedTests=tests,grading=case.cfg,sourceHashes={},testsHashes={});job.root=case.job
   actual=g.run_job(job,'host');self.assertEqual(actual['classification'],'success');self.assertEqual(actual['score'],1);self.assertEqual(actual['variants']['wrong']['counts']['failed'],1)
  finally:case.doCleanups()
 def test_invalid_starter_cannot_bypass_compilation_gate_with_negative_expectation(self):
  r=result()
  for k in ['counts','score','maxPoints','rawResult','durations','diagnostics','toolchain','containment','scoring']:r.pop(k)
  r.update(gradable=False,studentCompilation='failure',trustedCompilation='not-run',classification='student-compilation-failure',format_errors='invalid source')
  self.assertEqual(g.verify_results([r],{'starter':{'student-compilation':'failure'}})['exitCode'],1)
 def test_schema_valid_forged_complete_coverage_fails_semantic_integrity(self):
  required=[{'qualifiedId':'demo/exr-a','scenario':'reference:default','optional':False},{'qualifiedId':'demo/exr-a','scenario':'starter','optional':False}]
  receipt=g.verify_results([result()],{},required);receipt['coverage']='complete';receipt['identityHash']=g.digest({k:v for k,v in receipt.items() if k!='identityHash'})
  g.validate('verification-receipt',receipt)
  with self.assertRaises(g.JobError):g.validate_receipt_integrity(receipt)
