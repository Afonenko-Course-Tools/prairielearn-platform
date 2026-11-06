"""Native package validation сохраняет реальные слоты и privacy без contentproof."""
import copy,json,shutil,sys,unittest
from unittest.mock import patch
from pathlib import Path
import test_delivery5 as fixtures
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
import delivery_verification as v
class DeliveryPackage(unittest.TestCase):
 setUp=fixtures.Delivery5.setUp
 put=fixtures.Delivery5.put
 def test_schema_validation_without_hash_manifest(self):
  schema_root=self.root/'schema-provider';folder=schema_root/'schemas/native-upstream'
  shutil.copytree(v.ROOT/'schemas/native-upstream',folder)
  (folder/'manifest.json').unlink(missing_ok=True)
  names={'infoCourse.json':'infoCourse.json','infoCourseInstance.json':'courseInstances/fixture/infoCourseInstance.json','infoAssessment.json':'courseInstances/fixture/assessments/lab/infoAssessment.json','infoQuestion.json':'questions/'+self.q+'/info.json'}
  with patch.object(v,'ROOT',schema_root):
   self.assertEqual(v.package_integrity(self.d,self.root)['status'],'success')
   for name,rel in names.items():
    value=json.loads((self.root/rel).read_text());v.native_schema(name,value)
    value['uuid']=17
    with self.subTest(schema=name),self.assertRaisesRegex(g.JobError,'Invalid native '+name):v.native_schema(name,value)
 def test_instance_names_and_catalog_guards(self):
  original=copy.deepcopy(self.d)
  for value in ['', '../escape','a/b','Upper',' bad','bad ']:
   self.d=copy.deepcopy(original);self.d['instances']={value:{'works':['lab'],'selfEnrollment':False}}
   with self.subTest(value=value),self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
 def test_manual_requires_upload_and_rejects_private_grader(self):
  for html in ['<p>Нет ввода</p>','<pl-file-upload file-names=""></pl-file-upload>','<pl-file-upload file-names="../secret"></pl-file-upload>','<pl-file-upload file-names="answer.txt"></pl-file-upload><pl-external-grader-results></pl-external-grader-results>']:
   self.put('questions/'+self.q+'/question.html',html)
   with self.subTest(html=html),self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
 def test_exact_catalog_and_actual_slots(self):
  d=copy.deepcopy(self.d);d['questions'].append(self.q)
  with self.assertRaises(g.JobError):v.package_integrity(d,self.root)
  path='courseInstances/fixture/assessments/lab/infoAssessment.json';a=json.loads((self.root/path).read_text());a['zones'][0]['questions'].append(copy.deepcopy(a['zones'][0]['questions'][0]));self.put(path,a)
  with self.assertRaises(g.JobError):v.package_integrity(self.d,self.root)
if __name__=='__main__':unittest.main()
