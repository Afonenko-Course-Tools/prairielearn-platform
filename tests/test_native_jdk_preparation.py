"""Только synthetic filesystem fixtures; не actual base/container/JDK admission."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def metadata(info):return {'uid':info.st_uid,'gid':info.st_gid,'mode':oct(stat.S_IMODE(info.st_mode)),'bytes':info.st_size,'nlink':info.st_nlink,'dev':info.st_dev,'inode':info.st_ino,'mtimeNs':info.st_mtime_ns,'ctimeNs':info.st_ctime_ns}

class NativeJdkPreparation(unittest.TestCase):
 def setUp(self):
  path=ROOT/'tools/prepare_native_jdk.py';self.assertTrue(path.is_file(),'Missing bounded operator JDK normalizer')
  spec=importlib.util.spec_from_file_location('prepare_native_jdk',path);self.tool=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.tool;spec.loader.exec_module(self.tool)
  temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
  self.source=self.root/'usr/lib/jvm/java-25-openjdk-amd64';self.source.mkdir(parents=True)
  self.destination=self.root/'normalized-jdk';self.missing=self.root/'usr/lib/jvm/openjdk-25'
  for directory in ('bin','lib','conf'):(self.source/directory).mkdir()
  self.external=self.root/'etc/java-25-openjdk/native.properties';self.external.parent.mkdir(parents=True);self.external.write_bytes(b'fixture.setting=true\n');self.external.chmod(0o440)
  self.docs=self.root/'usr/share/doc/fixture';(self.docs/'sub').mkdir(parents=True);(self.docs/'NOTICE').write_bytes(b'fixture notice\n');(self.docs/'sub/LICENSE').write_bytes(b'fixture license\n')
  self.content={'bin/java':b'UNIT ONLY java bytes','bin/javac':b'UNIT ONLY javac bytes','lib/modules':b'UNIT ONLY compiler modules','release':b'JAVA_VERSION="25-fixture"\nIMPLEMENTOR="Synthetic unit fixture"\n'}
  for name,data in self.content.items():(self.source/name).write_bytes(data);(self.source/name).chmod(0o755 if name.startswith('bin/') else 0o644)
  (self.source/'conf/config.properties').symlink_to(self.external);(self.source/'legal').symlink_to(self.docs,target_is_directory=True);(self.source/'lib/src.zip').symlink_to('../../openjdk-25/src.zip')
  self.names=('', 'bin','bin/java','bin/javac','conf','conf/config.properties','legal','legal/NOTICE','legal/sub','legal/sub/LICENSE','lib','lib/modules','lib/src.zip','release')
  self.policy=self.tool._Policy(owner_uid=os.geteuid(),trusted_root=self.root,missing_target=self.missing,proof_scope='synthetic-unit-fixture')
  self.admission=self.fixture_admission()
 def fixture_admission(self):
  # Expected logical set is independent of the production walker.
  logical={};files={};directories={};links={};omissions={}
  for name in self.names:
   path=self.source/name;origin=path.lstat();record={'lstat':metadata(origin),'type':'symlink' if path.is_symlink() else 'directory' if path.is_dir() else 'regular'};logical[name]=record
   if path.is_symlink():
    raw=os.readlink(os.fsencode(path));record['readlink']={'text':os.fsdecode(raw),'hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()};links[name]=record
   if name=='lib/src.zip':record['strictResolve']={'errno':2,'missingPath':str(self.missing)};omissions[name]=record;continue
   resolved=path.resolve(strict=True);info=resolved.stat();record['resolvedTarget']=str(resolved);record['targetStat']=metadata(info)
   if path.is_dir():record['members']=sorted(p.name for p in path.iterdir());directories[name]={'mode':oct(info.st_mode&0o755),'uid':os.geteuid()}
   else:record['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();files[name]={'sha256':record['sha256'],'bytes':info.st_size,'mode':oct(info.st_mode&0o755)}
  snapshot={'logical':logical,'files':files,'directories':directories,'links':links,'omissions':omissions};expected={'home':str(self.destination),'release':(self.source/'release').read_text(),'files':copy.deepcopy(files)}
  return {'sourceHome':str(self.source),'sourceBefore':snapshot,'sourceAfter':copy.deepcopy(snapshot),'sourceBeforeSha256':digest(snapshot),'sourceAfterSha256':digest(snapshot),'expectedNormalizedJdk':expected,'expectedNormalizedDirectories':directories,'expectedNormalizedJdkSha256':digest(expected),'actualNormalizedCopyCreated':False,'normalizedInstallationAdmission':False}
 def prepare(self,admission=None):return self.tool._prepare(self.source,self.destination,admission or self.admission,self.policy)
 def test_complete_fixture_copies_links_to_independent_regular_files_and_omits_exact_leaf(self):
  receipt=self.prepare();self.assertEqual(receipt['proofScope'],'synthetic-unit-fixture');self.assertFalse(receipt['normalizedInstallationAdmission'])
  self.assertEqual(set(receipt['normalizedFiles']),{'bin/java','bin/javac','lib/modules','release','conf/config.properties','legal/NOTICE','legal/sub/LICENSE'})
  self.assertEqual((self.destination/'conf/config.properties').read_bytes(),b'fixture.setting=true\n');self.assertEqual((self.destination/'legal/sub/LICENSE').read_bytes(),b'fixture license\n')
  self.assertFalse(os.path.lexists(self.destination/'lib/src.zip'));self.assertEqual(set(receipt['excludedNonPayload']),{'lib/src.zip'})
  for name,expected in self.admission['expectedNormalizedJdk']['files'].items():
   path=self.destination/name;info=path.lstat();self.assertTrue(stat.S_ISREG(info.st_mode));self.assertEqual(info.st_nlink,1);self.assertEqual(oct(stat.S_IMODE(info.st_mode)),expected['mode']);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),expected['sha256']);self.assertNotEqual((info.st_dev,info.st_ino),((self.source/name).stat().st_dev,(self.source/name).stat().st_ino))
  self.assertEqual(receipt['sourceBefore'],receipt['sourceAfter']);self.assertEqual(receipt['normalizedBefore'],receipt['normalizedAfter'])
 def test_unknown_or_changed_omission_fails_without_generic_ignore(self):
  for mutation in ('another','changed-text','missing','regular','resolvable'):
   with self.subTest(mutation=mutation):
    fixture=NativeJdkPreparation();fixture.setUp()
    try:
     leaf=fixture.source/'lib/src.zip'
     if mutation=='another':(fixture.source/'lib/other.zip').symlink_to('other-missing')
     elif mutation=='changed-text':leaf.unlink();leaf.symlink_to('../../other-jdk/src.zip')
     elif mutation=='missing':leaf.unlink()
     elif mutation=='regular':leaf.unlink();leaf.write_bytes(b'not a link')
     else:fixture.missing.mkdir();(fixture.missing/'src.zip').write_bytes(b'now resolvable')
     with fixture.assertRaises(fixture.tool.PreparationError):fixture.prepare()
    finally:fixture.doCleanups()
 def test_changed_source_expected_inventory_or_same_byte_link_target_refuses(self):
  for mutation in ('source','expected','retarget','extra','missing'):
   with self.subTest(mutation=mutation):
    fixture=NativeJdkPreparation();fixture.setUp()
    try:
     if mutation=='source':(fixture.source/'bin/java').write_bytes(b'changed source')
     elif mutation=='expected':fixture.admission['expectedNormalizedJdk']['files']['bin/java']['sha256']='0'*64;fixture.admission['expectedNormalizedJdkSha256']=digest(fixture.admission['expectedNormalizedJdk'])
     elif mutation=='retarget':other=fixture.external.parent/'same-bytes';other.write_bytes(fixture.external.read_bytes());other.chmod(0o440);(fixture.source/'conf/config.properties').unlink();(fixture.source/'conf/config.properties').symlink_to(other)
     elif mutation=='extra':(fixture.source/'Extra').write_bytes(b'extra')
     else:(fixture.source/'bin/javac').unlink()
     with fixture.assertRaises(fixture.tool.PreparationError):fixture.prepare()
    finally:fixture.doCleanups()
 def test_source_cycles_special_files_or_unsafe_modes_fail(self):
  for mutation in ('cycle','fifo','source-mode','source-parent','traversal'):
   with self.subTest(mutation=mutation):
    fixture=NativeJdkPreparation();fixture.setUp()
    try:
     if mutation=='cycle':(fixture.source/'loop').symlink_to(fixture.source,target_is_directory=True)
     elif mutation=='fifo':os.mkfifo(fixture.source/'fifo')
     elif mutation=='source-mode':(fixture.source/'bin/java').chmod(0o777)
     elif mutation=='source-parent':fixture.external.parent.chmod(0o777)
     else:fixture.admission['expectedNormalizedJdk']['files']['../escape']={'sha256':'0'*64,'bytes':1,'mode':'0o644'}
     with fixture.assertRaises(fixture.tool.PreparationError):fixture.prepare()
    finally:fixture.doCleanups()
 def test_existing_destination_symlink_or_unsafe_parent_refuses(self):
  self.destination.mkdir();(self.destination/'sentinel').write_bytes(b'keep')
  with self.assertRaises(self.tool.PreparationError):self.prepare()
  self.assertEqual((self.destination/'sentinel').read_bytes(),b'keep')
 def test_copy_substitution_restore_is_crossbound_to_admitted_bytes(self):
  original=self.tool.shutil.copyfileobj;target=self.source/'bin/java'
  def substitute(input_stream,output,*args):
   if os.fstat(input_stream.fileno()).st_ino==target.stat().st_ino:output.write(b'UNIT ONLY substituted copy bytes');return
   return original(input_stream,output,*args)
  with patch.object(self.tool.shutil,'copyfileobj',side_effect=substitute):
   with self.assertRaisesRegex(self.tool.PreparationError,'copied payload'):self.prepare()
 def test_copy_extra_symlink_or_hardlink_refuses(self):
  for mutation in ('extra','symlink','hardlink'):
   with self.subTest(mutation=mutation):
    fixture=NativeJdkPreparation();fixture.setUp();original=fixture.tool.shutil.copyfileobj
    try:
     def corrupt(input_stream,output,*args):
      identity=os.fstat(output.fileno());destination=next(path for path in fixture.destination.rglob('*') if path.is_file() and path.stat().st_ino==identity.st_ino)
      original(input_stream,output,*args)
      if mutation=='extra':(destination.parent/'extra').write_bytes(b'extra')
      else:
       source=next(path for path in fixture.source.rglob('*') if path.is_file() and path.stat().st_ino==os.fstat(input_stream.fileno()).st_ino)
       destination.unlink()
       if mutation=='hardlink':os.link(source,destination)
       else:destination.symlink_to(source)
     with patch.object(fixture.tool.shutil,'copyfileobj',side_effect=corrupt):
      with fixture.assertRaises(fixture.tool.PreparationError):fixture.prepare()
    finally:fixture.doCleanups()
 def test_source_links_changed_after_copy_are_detected_even_with_equal_bytes(self):
  original=self.tool.shutil.copyfileobj;other=self.external.parent/'same';other.write_bytes(self.external.read_bytes());other.chmod(0o440)
  def retarget(input_stream,output,*args):
   result=original(input_stream,output,*args)
   if os.fstat(input_stream.fileno()).st_ino==(self.source/'bin/java').stat().st_ino:(self.source/'conf/config.properties').unlink();(self.source/'conf/config.properties').symlink_to(other)
   return result
  with patch.object(self.tool.shutil,'copyfileobj',side_effect=retarget):
   with self.assertRaises(self.tool.PreparationError):self.prepare()
 def test_runtime_paths_and_production_admission_cannot_be_selected_by_fixture_flags(self):
  with self.assertRaises(self.tool.PreparationError):self.tool._validate_production_admission(b'{"fake":true}')

 def test_setid_and_sticky_source_modes_refuse_before_copy(self):
  for mode in (0o4755,0o2755,0o1755):
   with self.subTest(mode=oct(mode)):
    fixture=NativeJdkPreparation();fixture.setUp()
    try:
     (fixture.source/'bin/java').chmod(mode);fixture.admission=fixture.fixture_admission()
     with fixture.assertRaises(fixture.tool.PreparationError):fixture.prepare()
     fixture.assertFalse(fixture.destination.exists())
    finally:fixture.doCleanups()
 def test_receipt_must_be_outside_source_and_copy_trees(self):
  for receipt in (self.source/'receipt.json',self.destination/'receipt.json'):
   with self.subTest(receipt=receipt):
    with patch.object(self.tool.os,'geteuid',return_value=0),patch.object(self.tool.platform,'system',return_value='Linux'),patch.object(self.tool.platform,'machine',return_value='x86_64'),patch.object(self.tool,'SOURCE_HOME',self.source),patch.object(self.tool,'DESTINATION',self.destination),patch.object(self.tool,'_validate_production_admission',return_value=self.admission),patch.object(self.tool,'_parents'),patch.object(self.tool,'_prepare',return_value={}) as prepare:
     admission=self.root/'admission.json';admission.write_bytes(b'fixture only')
     with self.assertRaises(SystemExit):self.tool.main(['--admission',str(admission),'--receipt',str(receipt)])
     prepare.assert_not_called()
 def test_destination_symlink_and_writable_parent_refuse(self):
  self.destination.symlink_to(self.docs,target_is_directory=True)
  with self.assertRaises(self.tool.PreparationError):self.prepare()
  self.destination.unlink();self.root.chmod(0o777)
  with self.assertRaises(self.tool.PreparationError):self.prepare()
  self.root.chmod(0o700)


class CompletedTreeTests(unittest.TestCase):
 setUp=NativeJdkPreparation.setUp
 fixture_admission=NativeJdkPreparation.fixture_admission
 prepare=NativeJdkPreparation.prepare
 def test_complete_tree_preserves_hardened_bytes_and_limits_root_to_private_group(self):
  self.prepare();self.assertTrue(callable(getattr(self.tool,'_complete_tree',None)),'Missing protected completion operation')
  staging=self.root/'staging';staging.mkdir(mode=0o700)
  components={}
  for name in ['lib/libmanagement.so','lib/libmanagement_ext.so','lib/libmanagement_agent.so']:
   data=('SYNTHETIC '+name).encode();p=staging/Path(name).name;p.write_bytes(data);p.chmod(0o644);components[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':'0o644'}
  before={n:(self.destination/n).read_bytes() for n in self.admission['expectedNormalizedJdk']['files']}
  receipt=self.tool._complete_tree(self.source,self.destination,staging,self.admission['expectedNormalizedJdk']['files'],components,os.getgid(),self.policy)
  self.assertEqual(len(receipt['completedAfter']['files']),10);self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode),0o750)
  self.assertEqual(receipt['sourceBefore'],receipt['sourceAfter']);self.assertEqual(receipt['completedBefore'],receipt['completedAfter'])
  self.assertTrue(all((self.destination/n).read_bytes()==b for n,b in before.items()))
  self.assertFalse(any(os.path.lexists(self.source/n) for n in components))
 def test_extra_or_changed_completion_staging_does_not_add_jni(self):
  self.prepare();self.assertTrue(callable(getattr(self.tool,'_complete_tree',None)),'Missing closed completion operation')
  staging=self.root/'staging';staging.mkdir(mode=0o700);(staging/'unexpected').write_bytes(b'extra')
  with self.assertRaises(self.tool.PreparationError):self.tool._complete_tree(self.source,self.destination,staging,self.admission['expectedNormalizedJdk']['files'],{'lib/libmanagement.so':{'sha256':'0'*64,'bytes':4,'mode':'0o644'}},os.getgid(),self.policy)
  self.assertFalse(os.path.lexists(self.destination/'lib/libmanagement.so'))


class CompletionPackageTests(unittest.TestCase):
 """Synthetic tar fixtures test closed extraction, not signed package/native proof."""
 def setUp(self):
  import io,tarfile
  spec=importlib.util.spec_from_file_location('completion_tool',ROOT/'tools/prepare_native_jdk.py');self.t=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.t;spec.loader.exec_module(self.t)
  self.assertTrue(callable(getattr(self.t,'_read_completion_members',None)),'Missing closed same-build completion parser')
  self.io=io;self.tarfile=tarfile
  self.components={n:{'sha256':hashlib.sha256(n.encode()).hexdigest(),'bytes':len(n),'mode':'0o644'} for n in ['lib/libmanagement.so','lib/libmanagement_ext.so','lib/libmanagement_agent.so']}
  self.source={'release':{'sha256':hashlib.sha256(b'fixture-release').hexdigest(),'bytes':15,'mode':'0o644'}}
 def archive(self,mutation=None):
  b=self.io.BytesIO()
  with self.tarfile.open(fileobj=b,mode='w') as t:
   records=[('release',b'fixture-release'),*[(n,n.encode()) for n in self.components]]
   if mutation=='missing':records.pop()
   if mutation=='duplicate':records.append(records[-1])
   if mutation=='extra':records.append(('lib/other/libmanagement.so',b'extra'))
   if mutation=='traversal':records.append(('../escape',b'extra'))
   if mutation=='unrelated-link':
    m=self.tarfile.TarInfo('./usr/lib/debug/unrelated');m.type=self.tarfile.SYMTYPE;m.mode=0o777;m.linkname='same-build-target';t.addfile(m)
   for n,data in records:
    m=self.tarfile.TarInfo('./usr/lib/jvm/java-25-openjdk-amd64/'+n);m.size=len(data);m.mode=0o644;m.uid=m.gid=0
    if mutation=='overlap' and n=='release':data=b'changed-release';m.size=len(data)
    if mutation=='hash' and n.endswith('libmanagement.so'):data=b'changed';m.size=len(data)
    if mutation=='symlink' and n.endswith('libmanagement.so'):m.type=self.tarfile.SYMTYPE;m.linkname='/elsewhere';m.size=0
    t.addfile(m,self.io.BytesIO(data) if m.isfile() else None)
  b.seek(0);return b
 def test_extracts_only_three_and_compares_regular_overlap(self):
  r=self.t._read_completion_members(self.archive(),self.source,self.components)
  self.assertEqual(set(r['components']),{'lib/libmanagement.so','lib/libmanagement_ext.so','lib/libmanagement_agent.so'})
  self.assertEqual(r['overlap'],['release'])
  self.assertEqual(r['components']['lib/libmanagement.so'],b'lib/libmanagement.so')
 def test_unextracted_unrelated_package_link_does_not_become_a_filesystem_member(self):
  r=self.t._read_completion_members(self.archive('unrelated-link'),self.source,self.components)
  self.assertEqual(set(r['components']),set(self.components))
 def test_missing_duplicate_alternate_link_hash_overlap_and_traversal_refuse(self):
  for mutation in ['missing','duplicate','extra','traversal','symlink','hash','overlap']:
   with self.subTest(mutation=mutation):
    with self.assertRaises(self.t.PreparationError):self.t._read_completion_members(self.archive(mutation),self.source,self.components)
