"""Применимость src/dist hooks и атомарный отказ patcher; без Native/DB/Docker."""
import json,pathlib,shutil,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/native-credit-upstream'
class PatchControls(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='credit-patch-');self.root=pathlib.Path(self.tmp.name)
  self.records=json.loads((FIX/'SOURCE.json').read_bytes())['files']
  for rel in self.records:
   dest=self.root/(rel if rel.startswith('dist/')else 'src/'+rel);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(FIX/rel,dest)
 def tearDown(self):self.tmp.cleanup()
 def paths(self):return[self.root/(r if r.startswith('dist/')else 'src/'+r)for r in self.records]
 def run_patch(self):return subprocess.run([sys.executable,'-B',str(ROOT/'images/prairielearn/patch-recognized-credit.py'),str(self.root)],capture_output=True,timeout=10)
 def test_ten_native_src_dist_hooks_accept_unrelated_comments(self):
  for p in self.paths():p.write_text(p.read_text()+'\n// harmless upstream comment\n')
  result=self.run_patch();self.assertEqual(result.returncode,0,result.stderr)
  for p in self.paths():
   text=p.read_text();self.assertIn('// harmless upstream comment',text)
   if p.stem=='manualGrading':self.assertEqual(text.count('export { recognizeCredit as recognizePreviousCredit }'),1)
   else:self.assertEqual(text.count("import { applyRecognizedCredit }"),1);self.assertIn('await applyRecognizedCredit({ assessment_instance_id',text)
 def test_patched_native_aggregate_preserves_scoring_behavior(self):
  self.assertEqual(self.run_patch().returncode,0)
  result=subprocess.run(['node',str(ROOT/'tests/recognized-aggregate.test.mjs'),'--aggregate='+str(self.root/'dist/lib/assessment-grading.js')],capture_output=True,timeout=20)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
 def test_missing_native_boundary_refuses_before_any_file_write(self):
  p=self.paths()[-1];p.write_text(p.read_text().replace('export async function updateInstanceQuestionScore(', 'export async function renamedScore(',1));before={p:p.read_bytes()for p in self.paths()}
  self.assertNotEqual(self.run_patch().returncode,0);self.assertEqual(before,{p:p.read_bytes()for p in self.paths()})
 def test_duplicate_native_boundary_refuses_before_any_file_write(self):
  p=self.root/'src/lib/assessment.ts';p.write_text(p.read_text()+'\nconst pointsByZone = await computeAssessmentInstanceScoreByZone({ assessment_instance_id });\n');before={p:p.read_bytes()for p in self.paths()}
  self.assertNotEqual(self.run_patch().returncode,0);self.assertEqual(before,{p:p.read_bytes()for p in self.paths()})
 def test_duplicate_patch_refuses_without_duplicate_hooks(self):
  self.assertEqual(self.run_patch().returncode,0);before={p:p.read_bytes()for p in self.paths()}
  self.assertNotEqual(self.run_patch().returncode,0);self.assertEqual(before,{p:p.read_bytes()for p in self.paths()})
 def test_missing_native_file_io_failure_does_not_partially_patch(self):
  self.paths()[-1].unlink();before={p:p.read_bytes()for p in self.paths()if p.exists()}
  self.assertNotEqual(self.run_patch().returncode,0);self.assertEqual(before,{p:p.read_bytes()for p in self.paths()if p.exists()})
if __name__=='__main__':
 assert sys.dont_write_bytecode,'Python -B required'
 unittest.main()
