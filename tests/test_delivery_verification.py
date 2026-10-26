"""Package integrity is evidence of bytes/controls, never a manual score."""
from gradle_unit_fixtures import write_registry as unit_registry_file
from gradle_unit_fixtures import registry as unit_registry
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
import delivery_verification as v
class DeliveryPackage(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.q='demo/exr-manual';self.uuid='37d79ee7-fd7d-44db-bd45-6587711862a5'
  self.put('infoCourse.json',{'uuid':'4174cd08-ddff-4006-81cc-d7a6b67d3ee0','name':'FIXTURE','title':'Synthetic','timezone':'Europe/Minsk','topics':[{'name':'fixture','color':'gray1','description':'Synthetic'}]})
  self.put('questions/'+self.q+'/info.json',{'uuid':self.uuid,'type':'v3','title':'Manual fixture','topic':'fixture','gradingMethod':'Manual','showCorrectAnswer':False})
  self.put('questions/'+self.q+'/question.html','<p>Synthetic task</p><pl-file-upload file-patterns="*" optional-file-patterns="*"></pl-file-upload>')
  self.put('questions/'+self.q+'/clientFilesQuestion/README.md','PUBLIC_STARTER')
  self.put('courseInstances/fixture/infoCourseInstance.json',{'uuid':'b1017718-408e-410a-ae67-b525de725a6d','longName':'Synthetic'})
  self.put('courseInstances/fixture/assessments/lab/infoAssessment.json',{'uuid':'9af557f9-c196-46bd-b813-09036235e732','type':'Homework','title':'Manual fixture','set':'Homework','number':'1','zones':[{'questions':[{'id':self.q,'autoPoints':0,'manualPoints':2}]}]})
  self.delivery={'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'questions':[self.q],'gradingPayloads':{self.q:{'uuid':self.uuid,'grading':{'method':'manual'},'submission':{'mode':'upload'},'sourceRoot':'projects/manual'}}}
  self.checks={'schemaVersion':1,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[]};self.delivery.update(verificationInventoryHash=g.digest([]),works=[{'id':'lab','slots':[{'id':'demo/lab/exr-manual','selection':'fixed','candidates':[self.q],'assignment':{'requirement':'required','workMode':'individual'}}],'policy':{},'completion':{'schemaVersion':2,'mode':'required-slot-completion','source':'per-slot-results-v2','slotIds':['demo/lab/exr-manual'],'requiredSlotIds':['demo/lab/exr-manual'],'atLeast':1,'fullyCompletedScore':1}}],instances={'fixture':{'works':['lab'],'selfEnrollment':False}});self.refresh()
 def put(self,name,value):
  path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value if isinstance(value,str) else json.dumps(value))
 def refresh(self):
  self.delivery['files']={p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()};self.delivery['deliveryHash']=g.digest({k:x for k,x in self.delivery.items() if k!='deliveryHash'})
 def test_wholly_manual_package_is_nonempty_without_auto_job_or_score(self):
  proof=v.package_integrity(self.delivery,self.root,self.checks);self.assertEqual(proof['status'],'success');self.assertEqual(proof['questionBindings'][0]['method'],'manual');self.assertNotIn('score',proof)
  with self.assertRaises(g.JobError):g.verify_results([],{},registry=unit_registry())
 def test_manual_requires_real_upload_and_no_grader(self):
  html='questions/'+self.q+'/question.html';original=(self.root/html).read_text();self.put(html,'<pl-file-upload file-names="report.txt"></pl-file-upload>');self.refresh();v.package_integrity(self.delivery,self.root,self.checks);self.put(html,original);self.refresh()
  for path,value in [('question.html','<pl-file-upload file-names=""></pl-file-upload>'),('question.html','<pl-file-upload optional-file-names="../report.txt"></pl-file-upload>'),('question.html','<p>No input</p>'),('question.html','<pl-file-upload file-names="S.java"></pl-file-upload><pl-external-grader-results></pl-external-grader-results>'),('tests/grading-job.json',{}),('server.py','PRIVATE_GRADER')]:
   with self.subTest(path=path,value=value):
    folder=self.root/'questions'/self.q;before={p.relative_to(folder):p.read_bytes() for p in folder.rglob('*') if p.is_file()};self.put('questions/'+self.q+'/'+path,value);self.refresh()
    with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
    import shutil;shutil.rmtree(folder)
    for name,data in before.items():p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    self.refresh()
 def test_closed_classification_and_exact_catalog(self):
  for change in ['missing-method','extra-binding','duplicate-id','manual-runtime','old-delivery']:
   d=copy.deepcopy(self.delivery)
   if change=='missing-method':d['gradingPayloads'][self.q].pop('grading')
   if change=='extra-binding':d['gradingPayloads']['demo/exr-extra']=d['gradingPayloads'][self.q]
   if change=='duplicate-id':d['questions'].append(self.q)
   if change=='manual-runtime':d['gradingPayloads'][self.q]['runtime']='java25-junit-v1'
   if change=='old-delivery':d['schemaVersion']=2
   d['deliveryHash']=g.digest({k:x for k,x in d.items() if k!='deliveryHash'})
   with self.subTest(change=change),self.assertRaises(g.JobError):v.package_integrity(d,self.root,self.checks)
 def test_actual_assessment_must_match_bound_slot_and_instance(self):
  name='courseInstances/fixture/assessments/lab/infoAssessment.json';original=json.loads((self.root/name).read_text())
  for mutate in [lambda a:a['zones'][0].update(bestQuestions=1),lambda a:a['zones'][0].update(numberChoose=1),lambda a:a['zones'][0]['questions'].append(dict(a['zones'][0]['questions'][0]))]:
   changed=copy.deepcopy(original);mutate(changed);self.put(name,changed);self.refresh()
   with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
  self.put(name,original);self.refresh();self.delivery['instances']['fixture']['works']=['missing-work'];self.delivery['deliveryHash']=g.digest({k:x for k,x in self.delivery.items() if k!='deliveryHash'})
  with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
 def test_tamper_and_fake_downgrade_fail(self):
  self.put('questions/'+self.q+'/clientFilesQuestion/README.md','TAMPERED')
  with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
  self.refresh();self.checks['projects']=[{'qualifiedId':self.q,'check':{'runtime':'java25-junit-v1'}}]
  with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
 def test_manual_outer_receipt_is_explicit_na_and_old_proof_refused(self):
  receipt=v.delivery_receipt(self.delivery,self.root,self.checks,registry=unit_registry())
  self.assertEqual(receipt['schemaVersion'],3);self.assertEqual(receipt['automatic'],{'state':'not-applicable','reason':'all-questions-manual'});self.assertNotIn('score',json.dumps(receipt))
  g.validate_release_receipt(receipt,self.delivery,self.root,registry=unit_registry())
  broken=copy.deepcopy(receipt);broken['automatic']['receipt']={};broken['identityHash']=g.digest({k:x for k,x in broken.items() if k!='identityHash'})
  with self.assertRaises(g.JobError):g.validate_release_receipt(broken,self.delivery,self.root,registry=unit_registry())
  with self.assertRaises(g.JobError):g.validate_release_receipt({'schemaVersion':1},self.delivery,self.root,registry=unit_registry())
 def test_mixed_plus_manual_requires_nonempty_auto_proof_for_only_mixed(self):
  import shutil,test_review_receipts as review
  manual='demo/exr-second';self.delivery['questions'].append(manual)
  source=self.root/'questions'/self.q;target=self.root/'questions'/manual;shutil.copytree(source,target)
  other_uuid='8cb757ae-6f14-467a-83cf-c1cfcb65d116';info=json.loads((target/'info.json').read_text());info['uuid']=other_uuid;self.put('questions/'+manual+'/info.json',info)
  self.delivery['gradingPayloads'][manual]={'uuid':other_uuid,'grading':{'method':'manual'},'submission':{'mode':'upload'},'sourceRoot':'projects/second'}
  image='synthetic@sha256:'+'a'*64;registry=unit_registry();registry['profiles']['java25-junit-v1']['image']=image
  info=json.loads((source/'info.json').read_text());info.update(gradingMethod='External',externalGradingOptions={'enabled':True,'image':image});self.put('questions/'+self.q+'/info.json',info)
  self.put('questions/'+self.q+'/question.html','<pl-file-upload file-names="S.java"></pl-file-upload><pl-external-grader-results></pl-external-grader-results>')
  descriptor={'schemaVersion':1,'sourceFiles':['S.java'],'testFiles':['T.java'],'mode':'implementation','runtime':'java25-junit-v1','java':{'release':25,'encoding':'UTF-8','compiler-options':['-proc:none','-Xmaxerrs','5']},'limits':{'outer-seconds':30,'compile-seconds':15,'run-seconds':10,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
  self.put('questions/'+self.q+'/tests/grading-job.json',descriptor)
  binding=self.delivery['gradingPayloads'][self.q];binding.update(grading={'method':'mixed'},runtime='java25-junit-v1',projectCheck='junit',sources=[{'projectRelativePath':'student/S.java','submissionRelativePath':'S.java','sha256':'c'*64}])
  self.checks['projects']=[{'qualifiedId':self.q,'projectRoot':binding['sourceRoot'],'check':{'runtime':'java25-junit-v1','profile':'junit'},'sources':binding['sources']}]
  work=self.delivery['works'][0];slot='demo/lab/exr-second';work['slots'].append({'id':slot,'selection':'fixed','candidates':[manual],'assignment':{'requirement':'required','workMode':'individual'}});work['completion']['slotIds'].append(slot);work['completion']['requiredSlotIds'].append(slot)
  name='courseInstances/fixture/assessments/lab/infoAssessment.json';assessment=json.loads((self.root/name).read_text());assessment['zones'][0]['questions']=[{'id':self.q,'autoPoints':7,'manualPoints':3},{'id':manual,'autoPoints':0,'manualPoints':10}];self.put(name,assessment)
  scenarios=[{'qualifiedId':self.q,'scenario':name,'optional':False} for name in ['contract:counterexample','reference:default','starter']];self.delivery['verificationInventoryHash']=g.digest(scenarios);self.refresh()
  with self.assertRaises(g.JobError):v.delivery_receipt(self.delivery,self.root,self.checks,registry=unit_registry())
  results=[]
  for scenario in scenarios:
   result=review.result(scenario['scenario'],image);result.update(qualifiedId=self.q,deliveryHash=self.delivery['deliveryHash']);results.append(result)
  automatic=g.verify_results(results,{},scenarios,registry=unit_registry());proof=v.delivery_receipt(self.delivery,self.root,self.checks,automatic,registry)
  self.assertEqual(proof['automatic']['receipt']['checkedIds'],[self.q]);self.assertEqual({row['method'] for row in proof['packageIntegrity']['questionBindings']},{'mixed','manual'})
  broken=copy.deepcopy(proof);broken['automatic']={'state':'not-applicable','reason':'all-questions-manual'};broken['identityHash']=g.digest({k:x for k,x in broken.items() if k!='identityHash'})
  with self.assertRaises(g.JobError):g.validate_release_receipt(broken,self.delivery,self.root,registry)
  html='questions/'+self.q+'/question.html';original=(self.root/html).read_text()
  for attrs in ['file-names="Wrong.java"','file-names=""','file-names="S.java,S.java"','file-names="S.java" optional-file-names="secret.txt"','file-patterns="*"','optional-file-names="S.java"','file-names="../S.java"']:
   self.put(html,'<pl-file-upload '+attrs+'></pl-file-upload><pl-external-grader-results></pl-external-grader-results>');self.refresh()
   with self.subTest(attrs=attrs),self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
  descriptor['additionalJavaSources']={'archive':'additional-sources.zip','maxFiles':8,'maxFileBytes':1024,'maxTotalBytes':4096,'maxArchiveBytes':4096}
  self.put('questions/'+self.q+'/tests/grading-job.json',descriptor)
  self.put(html,original.replace('file-names="S.java"','file-names="S.java" optional-file-names="additional-sources.zip"'));self.refresh();v.package_integrity(self.delivery,self.root,self.checks)
  descriptor['additionalJavaSources']['primaryRequired']=False
  self.put('questions/'+self.q+'/tests/grading-job.json',descriptor)
  self.put(html,original.replace('file-names="S.java"','optional-file-names="S.java,additional-sources.zip"'));self.refresh();v.package_integrity(self.delivery,self.root,self.checks)
  for attrs in ['file-names="S.java" optional-file-names="additional-sources.zip"','optional-file-names="additional-sources.zip"','optional-file-names="S.java,additional-sources.zip,Other.java"']:
   self.put(html,'<pl-file-upload '+attrs+'></pl-file-upload><pl-external-grader-results></pl-external-grader-results>');self.refresh()
   with self.subTest(optional_attrs=attrs),self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
  nested={**binding['sources'][0],'projectRelativePath':'student/pkg/Nested.java','submissionRelativePath':'pkg/Nested.java'}
  binding['sources'].append(nested);descriptor['sourceFiles'].append('pkg/Nested.java')
  self.put('questions/'+self.q+'/tests/grading-job.json',descriptor)
  self.put(html,original.replace('file-names="S.java"','optional-file-names="S.java,additional-sources.zip"'));self.refresh();v.package_integrity(self.delivery,self.root,self.checks)
  self.put(html,original.replace('file-names="S.java"','optional-file-names="S.java,pkg/Nested.java,additional-sources.zip"'));self.refresh()
  with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
  binding['sources'].pop();descriptor['sourceFiles'].pop()
  descriptor.pop('additionalJavaSources');self.put('questions/'+self.q+'/tests/grading-job.json',descriptor)
  self.put(html,original);self.refresh()
  assessment['zones'][0]['questions'][0].pop('manualPoints');self.put(name,assessment);self.refresh()
  with self.assertRaises(g.JobError):v.package_integrity(self.delivery,self.root,self.checks)
 def test_wholly_manual_cli_issues_package_envelope_and_subset_is_diagnostic(self):
  import subprocess
  with tempfile.TemporaryDirectory() as tmp:
   control=Path(tmp);manifest=control/'checks.json';manifest.write_text(json.dumps(self.checks));(self.root/'delivery.json').write_text(json.dumps(self.delivery));output=control/'report.json'
   command=[sys.executable,str(Path(g.__file__).parent/'check-course.py'),'verify','--manifest',str(manifest),'--snapshot',str(self.root),'--scope','delivery','--delivery',str(self.root/'delivery.json'),'--output',str(output),'--runtime-registry',str(unit_registry_file(control))]
   result=subprocess.run(command,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr);report=json.loads(output.read_text());self.assertEqual(report['results'],[]);self.assertEqual(report['receipt']['automatic']['state'],'not-applicable')
   result=subprocess.run(command+['--scenario','starter'],capture_output=True,text=True);self.assertEqual(result.returncode,1,result.stdout+result.stderr);report=json.loads(output.read_text());self.assertNotIn('receipt',report);self.assertEqual(report['coverage'],'partial')
