"""Native package validation сохраняет реальные слоты и privacy без contentproof."""
import copy,json,sys,unittest
from pathlib import Path
import test_delivery5 as fixtures
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import grading_job as g
import delivery_verification as v
class DeliveryPackage(unittest.TestCase):
 setUp=fixtures.Delivery5.setUp
 put=fixtures.Delivery5.put
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
