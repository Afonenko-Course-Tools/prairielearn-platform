"""Actual frozen C seed, synthetic Workspace authority; production reader не исполняет Git."""
import copy,hashlib,json,os,shutil,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_delivery4_corrections as helpers

class WorkspaceIndexTail(unittest.TestCase):
 def test_actual_tail_dispatch_all_three_readers_and_git(self):
  source,original=helpers.load('workspace');base=helpers.seed_entries(source,original);raw=base['work/.git/index'];end=raw.index(b'\0',74)
  with patch('subprocess.run',side_effect=AssertionError('Production child')):
   clean_receipt=helpers.v.delivery_receipt(original,source,helpers.checks(original),registry=helpers.authority(original))
  variants=[('clean',b'',True),('ctime',b'',True),('padding',b'',True),('optional-TEST',b'TEST'+struct.pack('>I',0),True),('optional-Test',b'Test'+struct.pack('>I',0),True),('optional-oversize',b'TEST'+struct.pack('>I',1048576),True),('mandatory-fail',b'fail'+struct.pack('>I',0),False),('optional-then-mandatory',b'TEST'+struct.pack('>I',0)+b'fail'+struct.pack('>I',0),False),('mandatory-oversize',b'fail'+struct.pack('>I',1048576),False),('optional-oversize-skips-fail',b'TEST'+struct.pack('>I',1048576)+b'fail'+struct.pack('>I',0),True),('short-tail',b'fail',True),('bad-footer',b'',False)]
  rows=[]
  for name,tail,expected in variants:
   with tempfile.TemporaryDirectory(prefix='workspace-tail-') as tmp:
    root=Path(tmp)/'native';shutil.copytree(source,root);d=copy.deepcopy(original);entries=dict(base);index=bytearray(raw[:-20]+tail+raw[-20:])
    if name=='ctime':struct.pack_into('>I',index,12,1234567)
    if name=='padding':index[end+1]=1
    index[-20:]=hashlib.sha1(index[:-20]).digest()
    if name=='bad-footer':index[-1]^=1
    entries['work/.git/index']=bytes(index);helpers.rewrite(root,d,entries)
    # Закрытый forged receipt имеет matching hashes; receiver обязан проверить actual index.
    forged=copy.deepcopy(clean_receipt);forged['deliveryHash']=d['deliveryHash'];forged['nativeAnswers']['deliveryHash']=d['deliveryHash'];forged['packageIntegrity']['filesHash']=helpers.g.digest(d['files']);q=d['questions'][0];prefix='questions/'+q+'/';files={n[len(prefix):]:sha for n,sha in d['files'].items() if n.startswith(prefix)};forged['packageIntegrity']['questionBindings'][0]['questionFilesHash']=helpers.g.digest(files);forged['identityHash']=helpers.g.digest({k:v for k,v in forged.items() if k!='identityHash'})
    calls=[]
    with patch('subprocess.run',side_effect=AssertionError('Production reader spawned child')):
     for receiver,call in [('package_integrity',lambda:helpers.v.package_integrity(d,root)),('delivery_receipt',lambda:helpers.v.delivery_receipt(d,root,helpers.checks(d),registry=helpers.authority(d))),('validate_release_receipt',lambda:helpers.g.validate_release_receipt(forged,d,root,helpers.authority(d)))]:
      accepted=True;error=''
      try:call()
      except helpers.g.JobError as e:accepted=False;error=str(e)
      calls.append({'reader':receiver,'accepted':accepted,'error':error,'actuallyCalled':True})
    work=Path(tmp)/'git-seed'
    for n,data in entries.items():path=work/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    argv=['diff','--no-ext-diff','--no-textconv','--cached','--raw','HEAD'];actual=helpers.git(work/'work',*argv)
    rows.append({'name':name,'expectedAccepted':expected,'receivers':calls,'git':{'argv':['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*argv],'exit':actual.returncode,'stdout':actual.stdout,'stderr':actual.stderr,'terminal':True},'readerChildren':0,'validIndexFooter':hashlib.sha1(index[:-20]).digest()==index[-20:]})
  helpers.record('tail-controls',rows)
  self.assertTrue(all(all(c['accepted']==r['expectedAccepted'] for c in r['receivers']) for r in rows),rows)
  for row in rows:
   if row['expectedAccepted']:self.assertEqual(row['git']['exit'],0,row);self.assertEqual(row['git']['stdout'],'',row)
   elif row['name']!='bad-footer':self.assertEqual(row['git']['exit'],128,row);self.assertIn('index uses fail extension',row['git']['stderr'])
if __name__=='__main__':unittest.main()
