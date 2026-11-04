"""Функциональная поставка Native сохраняет UUID, выбор и приватность без proof."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
import delivery_verification as v
class Delivery5(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);q='demo/exr-manual';self.q=q
  self.put('infoCourse.json',{'uuid':'4174cd08-ddff-4006-81cc-d7a6b67d3ee0','name':'FIXTURE','title':'Проба','timezone':'Europe/Minsk','topics':[{'name':'fixture','color':'gray1','description':'Проба'}]})
  self.put('questions/'+q+'/info.json',{'uuid':'37d79ee7-fd7d-44db-bd45-6587711862a5','type':'v3','title':'Ручной ответ','topic':'fixture','gradingMethod':'Manual','showCorrectAnswer':False})
  self.put('questions/'+q+'/question.html','<pl-file-upload file-patterns="*" optional-file-patterns="*"></pl-file-upload>')
  self.put('questions/'+q+'/clientFilesQuestion/README.md','Открытые материалы')
  self.put('courseInstances/fixture/infoCourseInstance.json',{'uuid':'b1017718-408e-410a-ae67-b525de725a6d','longName':'Проба'})
  self.put('courseInstances/fixture/assessments/lab/infoAssessment.json',{'uuid':'9af557f9-c196-46bd-b813-09036235e732','type':'Homework','title':'Проба','set':'Homework','number':'1','zones':[{'questions':[{'id':q,'autoPoints':0,'manualPoints':2}]}]})
  slot='demo/lab/exr-manual'
  self.d={'schemaVersion':5,'courseId':'demo','bookRoot':'tasks','questions':[q],'gradingPayloads':{q:{'kind':'project','uuid':'37d79ee7-fd7d-44db-bd45-6587711862a5','grading':{'method':'manual'},'submission':{'mode':'upload'},'sourceRoot':'projects/manual'}},'works':[{'id':'lab','slots':[{'id':slot,'selection':'fixed','candidates':[q],'assignment':{'requirement':'required','workMode':'individual'}}],'policy':{},'completion':{'schemaVersion':2,'mode':'required-slot-completion','source':'per-slot-results-v2','slotIds':[slot],'requiredSlotIds':[slot],'atLeast':1,'fullyCompletedScore':1}}],'instances':{'fixture':{'works':['lab'],'selfEnrollment':False}},'files':sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file())}
 def put(self,name,value):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value if isinstance(value,str) else json.dumps(value))
 def test_selected_file_list_works_without_hash_or_receipt(self):
  report=v.package_integrity(self.d,self.root);self.assertEqual(report['status'],'success');self.assertEqual(report['questionBindings'][0]['uuid'],self.d['gradingPayloads'][self.q]['uuid']);self.assertNotIn('Hash',json.dumps(report));self.assertNotIn('score',report)
 def test_updated_public_bytes_need_no_refresh_certificate(self):
  self.put('questions/'+self.q+'/clientFilesQuestion/README.md','Обновлённые материалы');self.assertEqual(v.package_integrity(self.d,self.root)['status'],'success')
 def test_manual_cannot_hide_grader_or_private_tests(self):
  self.put('questions/'+self.q+'/tests/secret.java','PRIVATE')
  with self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
 def test_native_uuid_and_actual_slot_bindings_still_checked(self):
  self.d['gradingPayloads'][self.q]['uuid']='66baa636-0dd7-4658-aa90-c9f893181d29'
  with self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
 def test_optional_zero_weight_mixed_question_keeps_native_grader_and_required_weight(self):
  import shutil
  import test_selected_file_delivery as selected
  from gradle_unit_fixtures import registry
  q2='demo/exr-required';shutil.copytree(self.root/'questions'/self.q,self.root/'questions'/q2)
  info=json.loads((self.root/'questions'/q2/'info.json').read_text());info['uuid']='66baa636-0dd7-4658-aa90-c9f893181d29';self.put('questions/'+q2+'/info.json',info)
  self.d['questions'].append(q2);self.d['gradingPayloads'][q2]=copy.deepcopy(self.d['gradingPayloads'][self.q]);self.d['gradingPayloads'][q2]['uuid']=info['uuid']
  work=self.d['works'][0];work['slots'][0]['assignment']['requirement']='optional';required='demo/lab/exr-required';work['slots'].append({'id':required,'selection':'fixed','candidates':[q2],'assignment':{'requirement':'required','workMode':'individual'}});work['completion'].update(slotIds=[s['id'] for s in work['slots']],requiredSlotIds=[required])
  m=selected.manifest();p=m['projects'][0];p.update(qualifiedId=self.q,projectRoot='projects/manual');job=g.prepare_job(m,self.root,self.q,'starter',registry=registry())
  self.addCleanup(lambda:shutil.rmtree(job.root));descriptor=job['grading']
  self.d['gradingPayloads'][self.q].update(grading={'method':'mixed'},submission={'mode':'editor'},projectCheck='junit',runtime='java25-junit-v1',sources=[{'projectRelativePath':'student/Answer.java','submissionRelativePath':'Answer.java'}])
  self.put('questions/'+self.q+'/tests/grading-job.json',descriptor);info=json.loads((self.root/'questions'/self.q/'info.json').read_text());info.update(gradingMethod='External',externalGradingOptions={'enabled':True,'image':job['imageDigest']});self.put('questions/'+self.q+'/info.json',info);self.put('questions/'+self.q+'/question.html','<pl-file-editor file-name="Answer.java"></pl-file-editor><pl-external-grader-results></pl-external-grader-results>')
  path='courseInstances/fixture/assessments/lab/infoAssessment.json';a=json.loads((self.root/path).read_text());a['zones']=[{'questions':[{'id':self.q,'autoPoints':0,'manualPoints':0}]},{'questions':[{'id':q2,'autoPoints':0,'manualPoints':2}]}];self.put(path,a)
  self.d['files']=sorted(f.relative_to(self.root).as_posix() for f in self.root.rglob('*') if f.is_file());self.assertEqual(v.package_integrity(self.d,self.root,m)['status'],'success')
 def test_selected_paths_cannot_escape_or_follow_symlink(self):
  for name in ['../secret','/absolute','C:/evil','a\\b']:
   with self.subTest(name=name),self.assertRaises(g.JobError):v.package_integrity(dict(self.d,files=[name]),self.root)
  (self.root/'linked').symlink_to('/etc/passwd');self.d['files'].append('linked')
  with self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
if __name__=='__main__':unittest.main()
