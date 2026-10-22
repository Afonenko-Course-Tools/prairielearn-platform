"""Synthetic host preparation boundaries; no Docker, JVM, downloads or installers."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'tools/prepare_native_toolchain.py'

class PreparationBoundaries(unittest.TestCase):
 def setUp(self):
  self.assertTrue(SCRIPT.is_file(),'Versioned host preparer is missing')
  spec=importlib.util.spec_from_file_location('native_context_preparer',SCRIPT);self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.root.chmod(0o700)
 def test_regular_read_rejects_wrong_hash_link_and_unsafe_mode(self):
  f=self.root/'input';f.write_bytes(b'abc');f.chmod(0o600)
  self.assertEqual(self.p.read_regular(f,{'bytes':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}),b'abc')
  with self.assertRaises(ValueError):self.p.read_regular(f,{'bytes':3,'sha256':'0'*64})
  link=self.root/'link';link.symlink_to(f)
  with self.assertRaises((ValueError,OSError)):self.p.read_regular(link)
  hard=self.root/'hard';os.link(f,hard)
  with self.assertRaises(ValueError):self.p.read_regular(f)
  hard.unlink();f.chmod(0o666)
  with self.assertRaises(ValueError):self.p.read_regular(f)
 def test_parent_symlink_and_writable_parent_are_rejected(self):
  d=self.root/'actual';d.mkdir(mode=0o700);f=d/'x';f.write_bytes(b'a');l=self.root/'alias';l.symlink_to(d)
  with self.assertRaises(ValueError):self.p.read_regular(l/'x')
  d.chmod(0o777)
  with self.assertRaises(ValueError):self.p.read_regular(f)
 def test_dotdot_input_is_not_lexically_normalized_past_a_parent_boundary(self):
  d=self.root/'child';d.mkdir(mode=0o700);f=self.root/'input';f.write_bytes(b'abc')
  with self.assertRaises(ValueError):self.p.read_regular(d/'..'/'input')
 def test_stanza_requires_one_exact_signed_package_identity(self):
  record={'Package':'demo','Version':'1','Architecture':'amd64','Filename':'pool/demo.deb','Size':'3','SHA256':'abc'}
  text='\n'.join(k+': '+v for k,v in record.items())+'\n\n'
  self.assertEqual(self.p.package_stanza(text,record),record)
  for bad in [text+text,text.replace('Version: 1','Version: 2'),text.replace('Size: 3','Size: 4'),text.replace('SHA256: abc','SHA256: wrong')]:
   with self.subTest(bad=bad),self.assertRaises(ValueError):self.p.package_stanza(bad,record)
 def test_manifest_rejects_extra_missing_changed_mode_and_bytes(self):
  d=self.root/'context';d.mkdir(mode=0o700);f=d/'a';f.write_bytes(b'abc');f.chmod(0o600)
  expected={'a':{'bytes':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad','mode':'0o600'}}
  self.p.verify_files(d,expected)
  extra=d/'extra';extra.write_bytes(b'');
  with self.assertRaises(ValueError):self.p.verify_files(d,expected)
  extra.unlink();f.chmod(0o644)
  with self.assertRaises(ValueError):self.p.verify_files(d,expected)
  f.chmod(0o600);f.write_bytes(b'abd')
  with self.assertRaises(ValueError):self.p.verify_files(d,expected)
  f.unlink()
  with self.assertRaises(ValueError):self.p.verify_files(d,expected)
 def test_publish_never_replaces_existing_empty_output_or_symlink(self):
  stage=self.root/'stage';stage.mkdir(mode=0o700);out=self.root/'out';out.mkdir(mode=0o700)
  with self.assertRaises(FileExistsError):self.p.publish_new(stage,out)
  self.assertTrue(stage.is_dir());out.rmdir();out.symlink_to(stage)
  with self.assertRaises(FileExistsError):self.p.publish_new(stage,out)
  out.unlink();self.p.publish_new(stage,out);self.assertTrue(out.is_dir());self.assertFalse(stage.exists())
 def test_dirty_source_is_rejected_before_output(self):
  subprocess.run(['git','init','-q',str(self.root)],check=True)
  subprocess.run(['git','-C',str(self.root),'config','user.name','Synthetic Test'],check=True)
  subprocess.run(['git','-C',str(self.root),'config','user.email','synthetic@example.invalid'],check=True)
  (self.root/'a').write_text('a');subprocess.run(['git','-C',str(self.root),'add','a'],check=True);subprocess.run(['git','-C',str(self.root),'commit','-qm','fixture'],check=True)
  self.assertEqual(len(self.p.source_identity(self.root)['commit']),40)
  (self.root/'a').write_text('dirty')
  with self.assertRaises(ValueError):self.p.source_identity(self.root)
 def test_baked_views_have_exact_three_profiles_and_actual_dependency_pins(self):
  lock=json.loads((ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').read_text())
  expected,hardened=self.p.generated_locks(lock)
  self.assertEqual(self.p.digest_bytes(expected),'c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca')
  self.assertEqual(self.p.digest_bytes(hardened),'bcde4c1c54c4c11cc6e55381a6bbf53df97968e644c986d3aa32676c552f231f')
  baked=self.p.baked_view(ROOT,expected)
  self.assertEqual(set(baked['profiles']),{'java25-junit-v1','java25-mutation-v1','java25-gradle-junit-v1'})
  for profile in baked['profiles'].values():
   self.assertNotIn('image',profile);self.assertEqual(profile['runnerSha256'],'05aa5dfe0889c48b57eacf665c4274ac18d9ac3b1a0f18f4a948cc09fba7a737')
  changed=json.loads(expected);changed['jdk']['files'].pop('lib/libmanagement.so')
  with self.assertRaises(ValueError):self.p.generated_locks(changed)
 def test_declared_manifest_cannot_reauthorize_tampered_installer_or_helper(self):
  declared=self.p.expected_payload_records(ROOT)
  self.assertEqual(declared['landlock_sandbox']['sha256'],'81cd81b6483feabf539ee28bd4697ddc51db228e63122cbc0408f588a94c6aef')
  self.p.validate_declared_payloads(ROOT,declared)
  for name in ['operator/install-native.py','landlock_sandbox','operator/components/libmanagement.so','gradle-9.8.0-bin.zip']:
   bad=json.loads(json.dumps(declared));bad[name]['sha256']='0'*64
   with self.subTest(name=name),self.assertRaises(ValueError):self.p.validate_declared_payloads(ROOT,bad)
 def test_closed_tar_has_only_selected_files_and_deterministic_root_metadata(self):
  import tarfile
  (self.root/'runtime').mkdir(mode=0o700);(self.root/'runtime/public').write_bytes(b'abc');(self.root/'private').write_bytes(b'NEVER_IN_CONTEXT')
  out=self.root/'one.tar';self.p.write_context_tar(self.root,out,{'runtime/public':{'bytes':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad','mode':'0o644'}})
  with tarfile.open(out) as archive:
   self.assertEqual(archive.getnames(),['runtime','runtime/public']);self.assertEqual(archive.extractfile('runtime/public').read(),b'abc')
   self.assertTrue(all(x.uid==x.gid==x.mtime==0 for x in archive));self.assertEqual(archive.getmember('runtime/public').mode,0o644)
  other=self.root/'two.tar';self.p.write_context_tar(self.root,other,{'runtime/public':{'bytes':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad','mode':'0o644'}});self.assertEqual(out.read_bytes(),other.read_bytes())
  with self.assertRaises(FileExistsError):self.p.write_context_tar(self.root,out,{})
 def test_invalid_signature_is_a_real_gpgv_refusal(self):
  keyring=ROOT/'images/java25-grader/toolchain/ubuntu-archive-keyring.gpg';bad=self.root/'bad-InRelease';bad.write_bytes(b'not a signed message')
  with self.assertRaises(ValueError):self.p.verified_inrelease(keyring,bad)

if __name__=='__main__':unittest.main()
