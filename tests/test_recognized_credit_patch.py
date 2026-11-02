"""Точные src/dist bytes и атомарный отказ patcher; без Native/DB/Docker."""
import hashlib,json,pathlib,shutil,subprocess,sys,tempfile,unittest
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
 def test_exact_ten_native_src_dist_files(self):
  result=self.run_patch();self.assertEqual(result.returncode,0,result.stderr)
  for rel,row in self.records.items():self.assertEqual(hashlib.sha256((self.root/(rel if rel.startswith('dist/')else 'src/'+rel)).read_bytes()).hexdigest(),row['patched_sha256'])
 def test_unrelated_native_drift_refuses_before_any_file_write(self):
  p=self.paths()[-1];p.write_bytes(p.read_bytes()+b'\n// unreviewed drift\n');before={p:p.read_bytes()for p in self.paths()}
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
