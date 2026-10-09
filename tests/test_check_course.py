"""Explicit inventory and snapshot authorization must fail closed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class InventoryTests(unittest.TestCase):
 def module(self):
  self.assertTrue((ROOT/'tools/grading_job.py').is_file(),'Shared manifest verification API is missing')
  spec=importlib.util.spec_from_file_location('grading_job',ROOT/'tools/grading_job.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_only_explicit_checks_are_in_inventory_and_ids_deduplicated(self):
  m=self.module();manifest={'schemaVersion':1,'courseId':'demo','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[{'qualifiedId':'demo/exr-a','projectRoot':'projects/a','check':{'profile':'junit'}},{'qualifiedId':'demo/exr-manual','projectRoot':'projects/manual'}]}
  self.assertEqual([p['qualifiedId'] for p in m.inventory(manifest)],['demo/exr-a'])
  manifest['projects'].append(manifest['projects'][0]);self.assertEqual(len(m.inventory(manifest)),1)
 def test_inventory_conflicting_duplicate_rejected(self):
  m=self.module();p={'qualifiedId':'demo/exr-a','projectRoot':'a','check':{'runtime':'java25-junit-v1'}}
  manifest={'schemaVersion':1,'projects':[p,dict(p,projectRoot='b')]}
  with self.assertRaises(m.JobError):m.inventory(manifest)
 def test_selected_incomplete_project_blocks_prepare(self):
  m=self.module();manifest={'schemaVersion':1,'courseId':'demo','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[{'qualifiedId':'demo/exr-a','projectRoot':'a','check':{'runtime':'java25-junit-v1'},'sources':[],'trustedTests':[]}]}
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(m.JobError):m.prepare_job(manifest,Path(d),'demo/exr-a','starter')
 def test_starter_failure_is_characterization_without_expectation(self):
  m=self.module();r={'qualifiedId':'demo/exr-a','scenario':'starter','classification':'behavior-failure','studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','score':0.5,'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'scope':'declared','runtime':'java25-junit-v1'}
  receipt=m.verify_results([r],{});self.assertEqual(receipt['status'],'success');self.assertEqual(receipt['exitCode'],0)
  receipt=m.verify_results([r],{'starter':{'required-tests':'all-pass'}});self.assertEqual(receipt['exitCode'],1)
 def test_infrastructure_never_becomes_success_receipt(self):
  m=self.module();r={'qualifiedId':'demo/exr-a','scenario':'starter','classification':'infrastructure-failure','infrastructure':'failure','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'scope':'declared','runtime':'java25-junit-v1'}
  self.assertEqual(m.verify_results([r],{})['exitCode'],2)
 def test_closed_scoring_union_rejects_unknown_fields(self):
  m=self.module();m.validate_profile({'runtime':'java25-junit-v1','scoring':{'mode':'weighted'}})
  with self.assertRaises(m.JobError):m.validate_profile({'runtime':'java25-junit-v1','scoring':{'mode':'weighted','groups':[]}})

class PreparedJobTests(unittest.TestCase):
 def module(self):
  spec=importlib.util.spec_from_file_location('grading_job',ROOT/'tools/grading_job.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_exact_payload_real_execution_validates_result_schema(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);project=root/'tasks/projects/a';(project/'student').mkdir(parents=True);(project/'tests').mkdir()
   files={'student/Student.java':'public class Student {public static int answer(){return 42;}}','tests/AnswerTest.java':'import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void right(){assertEquals(42,Student.answer());}}'}
   for name,text in files.items():(project/name).write_text(text)
   selection=lambda name,out:{'projectRelativePath':name,'submissionRelativePath':out,'sha256':hashlib.sha256((project/name).read_bytes()).hexdigest()}
   p={'qualifiedId':'synthetic/exr-a','projectRoot':'projects/a','check':{'runtime':'java25-junit-v1'},'sources':[selection('student/Student.java','Student.java')],'trustedTests':[selection('tests/AnswerTest.java','AnswerTest.java')]}
   manifest={'schemaVersion':1,'courseId':'synthetic','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[p]}
   job=m.prepare_job(manifest,root,'synthetic/exr-a','starter')
   try:
    r=m.run_job(job,'host');self.assertEqual(r['score'],1);m.validate('check-result',r)
   finally:__import__('shutil').rmtree(job.root)
   (project/'student/Student.java').write_text('changed')
   with self.assertRaises(m.JobError):m.prepare_job(manifest,root,'synthetic/exr-a','starter')

class PublicSuiteTests(PreparedJobTests):
 def test_public_verification_is_separate_non_scoring_evidence(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);project=root/'tasks/projects/a';(project/'student').mkdir(parents=True);(project/'tests').mkdir();(project/'public').mkdir()
   text={'student/Student.java':'public class Student {}','tests/OfficialTest.java':'import org.junit.jupiter.api.Test; public class OfficialTest { @Test void official(){} }','public/PublicTest.java':'import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class PublicTest { @Test void publicCheck(){fail("API missing");} }'}
   for name,value in text.items():(project/name).write_text(value)
   selection=lambda name,out:{'projectRelativePath':name,'submissionRelativePath':out,'sha256':hashlib.sha256((project/name).read_bytes()).hexdigest()}
   project_fact={'qualifiedId':'synthetic/exr-a','projectRoot':'projects/a','check':{'runtime':'java25-junit-v1'},'sources':[selection('student/Student.java','Student.java')],'trustedTests':[selection('tests/OfficialTest.java','OfficialTest.java')],'verificationTests':[selection('public/PublicTest.java','PublicTest.java')]}
   manifest={'schemaVersion':1,'courseId':'synthetic','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[project_fact]};job=m.prepare_job(manifest,root,'synthetic/exr-a','starter')
   try:
    r=m.run_job(job,'host');self.assertEqual(r['score'],1);self.assertIn('publicResult',r);self.assertEqual(r['publicResult']['counts']['failed'],1)
    receipt=m.verify_results([r],{'starter':{'required-tests':'all-pass'}});self.assertEqual(receipt['exitCode'],1)
   finally:__import__('shutil').rmtree(job.root)

class ReferenceReceiptTests(unittest.TestCase):
 def test_reference_failures_cannot_pass_without_explicit_expectations(self):
  m=InventoryTests().module();result={'qualifiedId':'synthetic/exr-a','scenario':'reference:default','scope':'declared','runtime':'java25-junit-v1','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'studentCompilation':'success','infrastructure':'complete','classification':'behavior-failure','counts':{'executed':1,'failed':1,'skipped':0,'aborted':0}}
  self.assertEqual(m.verify_results([result],{})['exitCode'],1)
