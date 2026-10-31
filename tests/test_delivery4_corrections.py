"""Адресные actual C package controls; carrier/authority только UNIT, не admission."""
import copy,hashlib,importlib.util,io,json,os,shutil,struct,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import delivery_verification as v,grading_job as g
import test_delivery_verification as legacy
spec=importlib.util.spec_from_file_location('corrected_builder',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
PACKAGES=Path(os.environ.get('PL_DELIVERY4_FIXTURES','/nonexistent'));EVIDENCE=Path(os.environ['PL_CORRECTION_EVIDENCE']) if os.environ.get('PL_CORRECTION_EVIDENCE') else None

def git(root,*args):
 env=dict(os.environ,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1')
 return subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args],cwd=root,env=env,capture_output=True,text=True,timeout=20)
def load(name):
 root=PACKAGES/name
 if not (root/'delivery.json').is_file():raise AssertionError('Fresh actual C package required: '+str(root))
 return root,json.loads((root/'delivery.json').read_text())
def checks(d):return dict(schemaVersion=1,projects=[],**{k:d[k] for k in ('sourceSnapshotHash','inventoryHash')})
def authority(d):return {'schemaVersion':2,'profiles':{},'workspaceImages':{'sp-git-workspace-v1':{'image':d['gradingPayloads'][d['questions'][0]]['submission']['workspaceOptions']['image']}}}
def seed_entries(root,d):
 q=d['questions'][0];prefix='questions/'+q+'/';b=d['gradingPayloads'][q]
 with zipfile.ZipFile(io.BytesIO((root/(prefix+b['seed']['archive'])).read_bytes())) as z:return {f.filename:z.read(f) for f in z.infolist()}
def rewrite(root,d,entries):
 q=d['questions'][0];prefix='questions/'+q+'/';b=d['gradingPayloads'][q];buf=io.BytesIO()
 with zipfile.ZipFile(buf,'w') as z:
  for n,data in entries.items():z.writestr(n,data)
 raw=buf.getvalue();b['seed']['archiveSha256']=hashlib.sha256(raw).hexdigest();manifest={'schema':b['seed']['schema'],'sha256':b['seed']['archiveSha256'],'files':[{'name':n,'sha256':hashlib.sha256(data).hexdigest()} for n,data in entries.items()]};mraw=json.dumps(manifest).encode();b['seed']['manifestSha256']=hashlib.sha256(mraw).hexdigest()
 for n,data in [(b['seed']['archive'],raw),(b['seed']['manifest'],mraw),('clientFilesQuestion/starter.zip',raw)]:
  (root/(prefix+n)).write_bytes(data);d['files'][prefix+n]=hashlib.sha256(data).hexdigest()
 d['deliveryHash']=g.digest({k:x for k,x in d.items() if k!='deliveryHash'});(root/'delivery.json').write_text(json.dumps(d))
def record(name,value):
 if EVIDENCE:EVIDENCE.mkdir(exist_ok=True);(EVIDENCE/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')

class WorkspaceIndex(unittest.TestCase):
 def test_actual_initial_index_and_semantic_mutants(self):
  source,original=load('workspace');base=seed_entries(source,original);raw=base['work/.git/index'];first=12;end=raw.index(b'\0',first+62);second=first+((end+1-first+7)//8)*8
  def put32(offset,value):return lambda b:struct.pack_into('>I',b,offset,value)
  def put16(offset,value):return lambda b:struct.pack_into('>H',b,offset,value)
  flags=struct.unpack('>H',raw[first+60:first+62])[0]
  variants=[('clean',lambda b:None,True),('stat-cache-only',put32(first,1234567),True),('symlink-mode',put32(first+24,0o120000),False),('executable-mode',put32(first+24,0o100755),False),('stage1',put16(first+60,flags|0x1000),False),('assume-valid',put16(first+60,flags|0x8000),False),('extended-flag',put16(first+60,flags|0x4000),False),('wrong-name-length',put16(first+60,1),False),('wrong-oid',lambda b:b.__setitem__(slice(first+40,first+60),bytes(20)),False),('wrong-path',lambda b:b.__setitem__(first+62,ord('Z')),False),('ignored-padding',lambda b:b.__setitem__(end+1,1),True),('excess-entry-count',put32(8,4097),False)]
  rows=[]
  for name,mutate,expected in variants:
   with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)/'native';shutil.copytree(source,root);d=copy.deepcopy(original);entries=dict(base);index=bytearray(raw);mutate(index);index[-20:]=hashlib.sha1(index[:-20]).digest();entries['work/.git/index']=bytes(index);rewrite(root,d,entries)
    accepted=False;error=''
    try:
     with patch('subprocess.run',side_effect=AssertionError('Production reader spawned child')):
      v.package_integrity(d,root);receipt=v.delivery_receipt(d,root,checks(d),registry=authority(d));g.validate_release_receipt(receipt,d,root,authority(d))
     accepted=True
    except g.JobError as e:error=str(e)
    work=Path(tmp)/'seed'
    for n,data in entries.items():p=work/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    actual=git(work/'work','diff','--cached','--raw','HEAD');rows.append({'name':name,'expectedAccepted':expected,'accepted':accepted,'error':error,'gitExit':actual.returncode,'gitDiff':actual.stdout,'gitError':actual.stderr,'productionChildren':0})
  record('index-controls',rows)
  self.assertTrue(all(r['accepted']==r['expectedAccepted'] for r in rows),rows)
  self.assertEqual(rows[0]['gitDiff'],'');self.assertIn('T\tREADME.md',next(r for r in rows if r['name']=='symlink-mode')['gitDiff'])

class BuildReader(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
  entry=self.source/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts';entry.parent.mkdir(parents=True);entry.write_text('// UNIT inert installed-exporter carrier; no native spawn\n')
  for args in [('init','-q'),('add','.'),('-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT carrier'),('remote','add','origin','https://example.invalid/unit-source')]:self.assertEqual(git(self.source,*args).returncode,0)
 def build(self,payload,d,manifest,label,assembly=None,mutate_source=False):
  calls=[];original=subprocess.run
  def carrier(args,*a,**kw):
   if args[0]=='quarto':
    assert args[1]=='run' and args[2].endswith('entrypoints/export-course.ts') and args[5:7]==['--instance','test']
    calls.append({'args':args,'cwd':str(kw['cwd']),'inertCarrierNotNativeSpawn':True});native=Path(args[4]);native.mkdir()
    for n in [*d['files'],'delivery.json']:
     path=native/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((payload/n).read_bytes())
    (native/'delivery.json').write_text(json.dumps(d));Path(args[args.index('--checks-output')+1]).write_text(json.dumps(manifest))
    if mutate_source:(self.source/'changed.qmd').write_text('changed during export')
    return subprocess.CompletedProcess(args,0)
   return original(args,*a,**kw)
  out=self.root/label;error='';accepted=False
  with patch('subprocess.run',carrier),patch.object(builder._assembly,'for_build',return_value=assembly):
   try:builder.build_course(self.source,'tasks','test',out);accepted=True
   except builder.BuildError as e:error=str(e)
  row={'label':label,'accepted':accepted,'error':error,'published':out.exists(),'privateChecksPublished':out.with_name(out.name+'-checks.json').exists(),'calls':calls};return row
 def test_actual_source_changed_fence_and_release3_capability_refuse4(self):
  from release_assembly_fixtures import AssemblyFixture
  root,d=load('numeric');changed=self.build(root,d,checks(d),'source-changed',mutate_source=True)
  self.assertFalse(changed['accepted']);self.assertFalse(changed['published']);self.assertFalse(changed['privateChecksPublished']);self.assertIn('Exporter changed clean source',changed['error']);(self.source/'changed.qmd').unlink()
  with tempfile.TemporaryDirectory() as tmp:
   f=AssemblyFixture(tmp);context=builder._assembly.Context(f.platform,f.assets/'images.lock.json')
   row=self.build(root,d,checks(d),'release3-cap',assembly=context)
   self.assertFalse(row['accepted']);self.assertFalse(row['published']);self.assertIn('source-bound release protocol',row['error']);record('source-release-fences',[changed,row])
 def test_actual_legacy3_and_native4_dispatch_mutants_and_final_fence(self):
  old=legacy.DeliveryPackage();old.setUp();self.addCleanup(old.doCleanups);old.put('delivery.json',old.delivery);rows=[self.build(old.root,old.delivery,old.checks,'legacy3')]
  project4=copy.deepcopy(old.delivery);project4['schemaVersion']=4
  for b in project4['gradingPayloads'].values():b['kind']='project'
  project4['deliveryHash']=g.digest({k:v for k,v in project4.items() if k!='deliveryHash'});rows.append(self.build(old.root,project4,old.checks,'project4'))
  for form in ('numeric','workspace'):
   root,d=load(form);rows.append(self.build(root,d,checks(d),form))
   for name,mutate in [('unknown-version',lambda x:x.update(schemaVersion=5)),('downgrade',lambda x:x.update(schemaVersion=3)),('unknown-kind',lambda x:x['gradingPayloads'][x['questions'][0]].update(kind='unknown')),('fake-codejob',lambda x:x['gradingPayloads'][x['questions'][0]].update(runtime='fake')),('check-identity',lambda x:x.update(inventoryHash='f'*64))]:
    bad=copy.deepcopy(d);mutate(bad);bad['deliveryHash']=g.digest({k:v for k,v in bad.items() if k!='deliveryHash'});rows.append(self.build(root,bad,checks(d),form+'-'+name))
  record('build-reader-controls',rows);self.assertTrue(all(r['accepted'] for r in rows if r['label'] in ('legacy3','project4','numeric','workspace')),rows);self.assertTrue(all(not r['accepted'] and not r['published'] and not r['privateChecksPublished'] for r in rows if r['label'] not in ('legacy3','project4','numeric','workspace')),rows)
if __name__=='__main__':unittest.main()
