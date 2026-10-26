"""Явный hash-pinned opt-in не создаёт verification receipt."""
import copy,hashlib,importlib.util,json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import stage_courses as s
class DeferredPolicy(unittest.TestCase):
 def test_paired_explicit_input_closed_record_and_expiry(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'p.json';policy={'mode':'package-integrity-user-deferred','automaticQualification':'DEFERRED_BY_USER','publicStatus':'NOT_VERIFIED','routeId':'demo','courseId':'demo','instance':'2026-2027-s1','repository':'https://example.invalid/demo.git','commit':'a'*40,'payloadHash':'b'*64,'deliveryHash':'c'*64,'sourceSnapshotHash':'d'*64,'inventoryHash':'e'*64,'verificationInventoryHash':'f'*64,'builder':{},'platformImagesHash':'1'*64,'questionCount':1,'workCount':1,'failedReportSha256':'2'*64,'humanDecisionSha256':'3'*64,'privacyAcceptanceSha256':'4'*64,'expiresAt':int(time.time())+600}
   def put(x):p.write_text(json.dumps(x));return hashlib.sha256(p.read_bytes()).hexdigest()
   sha=put(policy);self.assertEqual(s.load_admission_policy(p,sha),policy);self.assertIsNone(s.load_admission_policy(None,None))
   for path,digest in [(p,None),(None,sha),(p,'0'*64)]:
    with self.subTest(pair=(path,digest)),self.assertRaises(s.StorageError):s.load_admission_policy(path,digest)
   for key,value in [('mode','verified'),('automaticQualification','PASS'),('publicStatus','VERIFIED'),('expiresAt',int(time.time())-1),('expiresAt',True),('questionCount',0),('workCount',0),('humanDecisionSha256','nohash')]:
    bad=copy.deepcopy(policy);bad[key]=value;sha=put(bad)
    with self.subTest(field=key),self.assertRaises(s.StorageError):s.load_admission_policy(p,sha)
   bad=copy.deepcopy(policy);bad['extra']=1
   with self.assertRaises(s.StorageError):s.load_admission_policy(p,put(bad))
if __name__=='__main__':unittest.main()
