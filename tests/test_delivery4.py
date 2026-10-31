"""Actual C packages, bounded ordinary proofs; ни assignment admission, ни OCI."""
import copy,hashlib,io,json,os,shutil,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import delivery_verification as v,grading_job as g
from delivery4 import code_ids,seed_proof
import test_delivery_verification as legacy
FIXTURES=Path(os.environ.get('PL_DELIVERY4_FIXTURES','/nonexistent'))
def rehash(d):d['deliveryHash']=g.digest({k:x for k,x in d.items() if k!='deliveryHash'})
class Delivery4(unittest.TestCase):
 def load(self,form):
  root=FIXTURES/form
  if not (root/'delivery.json').is_file():self.fail('Actual C fixture required: '+str(root))
  return root,json.loads((root/'delivery.json').read_text())
 def test_actual_five_forms_package_receipt_replay_and_privacy(self):
  for form in ('manual','numeric','multipart','matching','single-choice'):
   with self.subTest(form=form):
    root,d=self.load(form);self.assertEqual(d['schemaVersion'],4);self.assertEqual(code_ids(d),set())
    checks={k:d[k] for k in ('sourceSnapshotHash','inventoryHash')};checks['projects']=[]
    receipt=v.delivery_receipt(d,root,checks);g.validate_release_receipt(receipt,d,root)
    self.assertEqual(len(receipt['nativeAnswers']['bindings']),1);self.assertEqual(receipt['automatic'],{'state':'not-applicable','reason':'no-project-automatic'})
    self.assertFalse(any(key in json.dumps(receipt) for key in ('734129','correct_answers','tolerance','"key"')))
    (root/'receipt-fixture.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    for mutate in (lambda r:r['nativeAnswers']['bindings'].clear(),lambda r:r['nativeAnswers']['bindings'].append(copy.deepcopy(r['nativeAnswers']['bindings'][0])),lambda r:r['nativeAnswers']['bindings'][0].update(uuid='00000000-0000-0000-0000-000000000000'),lambda r:r['nativeAnswers']['bindings'][0].update(serverSha256='f'*64),lambda r:r.update(automatic={'state':'verified','receipt':{}})):
     bad=copy.deepcopy(receipt);mutate(bad);bad['nativeAnswers']['inventoryHash']=g.digest(bad['nativeAnswers']['bindings']);bad['identityHash']=g.digest({k:x for k,x in bad.items() if k!='identityHash'})
     with self.assertRaises(g.JobError):g.validate_release_receipt(bad,d,root)
 def test_unbound_internal_controls_and_key_visibility_refuse(self):
  source,original=self.load('numeric');q=original['questions'][0];prefix='questions/'+q+'/'
  for mode in ('extra-control','secret-attribute','show-answer'):
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'native';shutil.copytree(source,root);d=copy.deepcopy(original)
    name=prefix+('info.json' if mode=='show-answer' else 'question.html');path=root/name
    if mode=='show-answer':
     info=json.loads(path.read_text());info['showCorrectAnswer']=True;path.write_text(json.dumps(info))
    else:path.write_text(path.read_text()+('<pl-checkbox answers-name="unbound"></pl-checkbox>' if mode=='extra-control' else '<pl-string-input answers-name="unbound" correct-answer="PRIVATE_SENTINEL"></pl-string-input>'))
    d['files'][name]=hashlib.sha256(path.read_bytes()).hexdigest();rehash(d)
    with self.assertRaises(g.JobError):v.package_integrity(d,root)
 def test_closed_kind_slots_grading_uuid_downgrade(self):
  root,d=self.load('numeric');q=d['questions'][0]
  changes=[lambda x:x['gradingPayloads'][q].pop('kind'),lambda x:x['gradingPayloads'][q].update(kind='unknown'),lambda x:x['gradingPayloads'][q].update(runtime='fake'),lambda x:x['gradingPayloads'][q].update(upstreamGradingMethod='External'),lambda x:x['gradingPayloads'][q]['grading'].update(method='manual'),lambda x:x['gradingPayloads'][q]['responseSlots'][0].update(name='foreign'),lambda x:x['gradingPayloads'][q]['responseSlots'][0].update(key=17),lambda x:x['gradingPayloads'][q].update(uuid='bad'),lambda x:x.update(schemaVersion=3),lambda x:x.update(schemaVersion=5)]
  for change in changes:
   bad=copy.deepcopy(d);change(bad);rehash(bad)
   with self.assertRaises(g.JobError):v.package_integrity(bad,root)
 def test_old3_and_project4_exact_shape(self):
  fixture=legacy.DeliveryPackage();fixture.setUp()
  try:
   old=fixture.delivery;v.package_integrity(old,fixture.root,fixture.checks)
   d=copy.deepcopy(old);d['schemaVersion']=4
   for b in d['gradingPayloads'].values():b['kind']='project'
   rehash(d);v.package_integrity(d,fixture.root,fixture.checks);receipt=v.delivery_receipt(d,fixture.root,fixture.checks);g.validate_release_receipt(receipt,d,fixture.root)
   for field in ('runtime','answerType','responseSlots'):
    bad=copy.deepcopy(d);bad['gradingPayloads'][fixture.q][field]='fake';rehash(bad)
    with self.assertRaises(g.JobError):v.classification(bad)
  finally:fixture.doCleanups()
 def test_project4_method_mode_closed_matrix(self):
  fixture=legacy.DeliveryPackage();fixture.setUp()
  try:
   for method in ('external','mixed','manual'):
    for mode in ('editor','upload'):
     d=copy.deepcopy(fixture.delivery);d['schemaVersion']=4;b=d['gradingPayloads'][fixture.q];b.update(kind='project',grading={'method':method},submission={'mode':mode})
     if method!='manual':b.update(projectCheck='junit',runtime='java25-junit-v1',sources=[{'projectRelativePath':'starter/Main.java','submissionRelativePath':'Main.java','sha256':'a'*64}])
     rehash(d)
     if method=='manual' and mode=='editor':
      with self.assertRaises(g.JobError):v.classification(d)
     else:self.assertEqual(v.classification(d),{fixture.q:method})
     for field in ('projectCheck','runtime','sources'):
      if method=='manual':continue
      bad=copy.deepcopy(d);bad['gradingPayloads'][fixture.q].pop(field);rehash(bad)
      with self.assertRaises(g.JobError):v.classification(bad)
  finally:fixture.doCleanups()
 def test_workspace_actual_seed_package_no_fake_job_and_image_gate(self):
  root,d=self.load('workspace');v.package_integrity(d,root);self.assertEqual(code_ids(d),set())
  checks={k:d[k] for k in ('sourceSnapshotHash','inventoryHash')};checks['projects']=[]
  with self.assertRaisesRegex(g.JobError,'Workspace image authority unqualified'):v.delivery_receipt(d,root,checks)
  image=d['gradingPayloads'][d['questions'][0]]['submission']['workspaceOptions']['image']
  synthetic={'schemaVersion':2,'profiles':{},'workspaceImages':{'sp-git-workspace-v1':{'image':image}}}
  receipt=v.delivery_receipt(d,root,checks,registry=synthetic);g.validate_release_receipt(receipt,d,root,synthetic)
  for registry in ({'schemaVersion':1,'profiles':{'fake':{'image':image}}},{'schemaVersion':2,'profiles':{},'workspaceImages':{}},{'schemaVersion':2,'profiles':{},'workspaceImages':{'unknown':{'image':image}}}):
   with self.assertRaises(g.JobError):g.validate_release_receipt(receipt,d,root,registry)
  bad=copy.deepcopy(d);bad['gradingPayloads'][d['questions'][0]]['grading']={'method':'external'};rehash(bad)
  with self.assertRaises(g.JobError):v.classification(bad)
 def test_workspace_zip_alias_origin_git_inventory_tamper(self):
  original,d=self.load('workspace');q=d['questions'][0];prefix='questions/'+q+'/'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'native';shutil.copytree(original,root)
   original_zip=(root/(prefix+'workspace/.pl-seed/starter.zip')).read_bytes()
   with zipfile.ZipFile(io.BytesIO(original_zip)) as z:entries={f.filename:z.read(f) for f in z.infolist()}
   for name,value in (('../escape',b'x'),('WORK/README.md',b'x'),('work/.git/HEAD',b'ref: refs/heads/foreign\n'),('work/.git/refs/heads/main',b'0'*40+b'\n'),('work/README.md',b'changed'),('work/extra.txt',b'extra')):
    changed=dict(entries);changed[name]=value;buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
     for n,data in changed.items():z.writestr(n,data)
    raw=buf.getvalue();bad=copy.deepcopy(d);b=bad['gradingPayloads'][q];b['seed']['archiveSha256']=hashlib.sha256(raw).hexdigest();manifest={'schema':b['seed']['schema'],'sha256':b['seed']['archiveSha256'],'files':[{'name':n,'sha256':hashlib.sha256(data).hexdigest()} for n,data in changed.items()]};mraw=json.dumps(manifest).encode();b['seed']['manifestSha256']=hashlib.sha256(mraw).hexdigest()
    for n,data in [('workspace/.pl-seed/starter.zip',raw),('workspace/.pl-seed/manifest.json',mraw),('clientFilesQuestion/starter.zip',raw)]:
     path=root/(prefix+n);path.write_bytes(data);bad['files'][prefix+n]=hashlib.sha256(data).hexdigest()
    rehash(bad)
    with self.subTest(name=name),self.assertRaises(g.JobError):v.package_integrity(bad,root)
if __name__=='__main__':unittest.main()
