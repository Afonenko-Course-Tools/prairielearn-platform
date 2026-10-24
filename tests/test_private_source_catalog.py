"""Публикационный каталог замораживается целиком до Git/receipt, без runtime."""
import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_private_source import GeneratedExecutionSource,stage,git,write

TARGET='_site-student/reference-catalog.json'
CATALOG=b'{ "schema": "quarto-reference-catalog", "targets": [1, 2] }\n'

class PublicationCatalog(unittest.TestCase):
 def fixture(self,root):
  p,e,c,out,r,m=GeneratedExecutionSource().fixture(root)
  with (p/'.gitignore').open('a') as stream:stream.write('_site-student/\n')
  git(p,'add','.gitignore');git(p,'-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','Ignore publication output')
  git(e,'fetch','-q',str(p),'HEAD');git(e,'reset','--hard','FETCH_HEAD');m['sourceCommit']=git(p,'rev-parse','HEAD');write(c/'materialization.json',json.dumps(m))
  catalog=root/'publication.json';catalog.write_bytes(CATALOG)
  return p,e,c,out,r,m,catalog
 def prepare(self,p,c,out,r,catalog):
  return stage.prepare(p,'tasks',c,out,r,publication_catalog=catalog)
 def test_whole_ignored_catalog_is_in_git_and_receipt_before_validation(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m,cat=self.fixture(Path(d))
   # Сам каталог игнорируется, но не исчезает из private Git tree.
   before={root:stage.physical_state(root) for root in [p,e,c]};original=stage.validate
   def check(*args,**kwargs):
    value=json.loads(r.read_bytes())
    self.assertEqual((out/TARGET).read_bytes(),CATALOG)
    self.assertEqual(value['files'][TARGET],hashlib.sha256(CATALOG).hexdigest())
    self.assertEqual(subprocess.check_output(['git','show','HEAD:'+TARGET],cwd=out),CATALOG)
    self.assertNotIn('_site-student',value['runtimeRoots'])
    return original(*args,**kwargs)
   with patch.object(stage,'validate',side_effect=check):value=self.prepare(p,c,out,r,cat)
   self.assertEqual(git(out,'status','--porcelain','--untracked-files=all'),'')
   self.assertEqual(cat.read_bytes(),CATALOG)
   self.assertEqual({root:stage.physical_state(root) for root in before},before)
   self.assertEqual(set(value),{'schema','publicBase','privateStage','materialization','seedFiles','seedStorage','runtimeRoots','files'})
 def test_omitted_option_preserves_existing_snapshot(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m,cat=self.fixture(Path(d));value=stage.prepare(p,'tasks',c,out,r)
   self.assertNotIn(TARGET,value['files']);self.assertFalse((out/TARGET).exists());stage.validate(out,r)
 def test_missing_symlink_and_special_inputs_fail_before_stage_creation(self):
  for kind in ['missing','symlink','parent-symlink','directory','hardlink']:
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
    root=Path(d);p,e,c,out,r,m,cat=self.fixture(root)
    if kind=='missing':cat.unlink()
    elif kind=='symlink':link=root/'link.json';link.symlink_to(cat);cat=link
    elif kind=='parent-symlink':link=root/'linked-parent';link.symlink_to(root,target_is_directory=True);cat=link/cat.name
    elif kind=='directory':cat.unlink();cat.mkdir()
    else:
     import os
     os.link(cat,root/'alias.json')
    with self.assertRaises((stage.StageError,OSError)):self.prepare(p,c,out,r,cat)
    self.assertFalse(out.exists());self.assertFalse(r.exists())
 def test_existing_tracked_catalog_is_not_clobbered(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m,cat=self.fixture(Path(d));write(p/TARGET,'TRACKED_CATALOG')
   git(p,'add','--force',TARGET);git(p,'-c','user.name=F','-c','user.email=f@example.invalid','commit','-qm','Catalog')
   git(e,'fetch','-q',str(p),'HEAD');git(e,'reset','--hard','FETCH_HEAD');m['sourceCommit']=git(p,'rev-parse','HEAD');write(c/'materialization.json',json.dumps(m))
   with self.assertRaises(stage.StageError):self.prepare(p,c,out,r,cat)
   self.assertEqual((p/TARGET).read_text(),'TRACKED_CATALOG');self.assertFalse(out.exists());self.assertFalse(r.exists())
 def test_catalog_change_during_freeze_rejects_and_cleans_only_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m,cat=self.fixture(Path(d));original=stage.validate
   def mutate(*args,**kwargs):cat.write_bytes(b'DRIFT');return original(*args,**kwargs)
   with patch.object(stage,'validate',side_effect=mutate):
    with self.assertRaises(stage.StageError):self.prepare(p,c,out,r,cat)
   self.assertFalse(out.exists());self.assertFalse(r.exists());self.assertTrue(p.exists() and e.exists() and c.exists())
 def test_output_receipt_and_catalog_cannot_alias(self):
  for which in ['output','receipt']:
   with self.subTest(which=which),tempfile.TemporaryDirectory() as d:
    p,e,c,out,r,m,cat=self.fixture(Path(d))
    if which=='output':out=cat
    else:r=cat
    with self.assertRaises(stage.StageError):self.prepare(p,c,out,r,cat)
    self.assertEqual(cat.read_bytes(),CATALOG)
 def test_cli_accepts_one_explicit_publication_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   p,e,c,out,r,m,cat=self.fixture(Path(d))
   result=subprocess.run(['/usr/bin/python3',str(Path(stage.__file__)),'--source',str(p),'--book','tasks','--materialized',str(c),'--output',str(out),'--receipt',str(r),'--publication-catalog',str(cat)],capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr.decode());self.assertEqual((out/TARGET).read_bytes(),CATALOG)
   second=out.parent/'ambiguous-stage';second_receipt=r.parent/'ambiguous-receipt.json'
   result=subprocess.run(['/usr/bin/python3',str(Path(stage.__file__)),'--source',str(p),'--book','tasks','--materialized',str(c),'--output',str(second),'--receipt',str(second_receipt),'--publication-catalog',str(cat),'--publication-catalog',str(cat)],capture_output=True)
   self.assertNotEqual(result.returncode,0);self.assertFalse(second.exists());self.assertFalse(second_receipt.exists())
