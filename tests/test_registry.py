import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'tools/check_registry.py'

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(),'Registry validator is not implemented')
        spec=importlib.util.spec_from_file_location('registry',SCRIPT)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.registry={'schema':'pl-courses-v1','courses':[{'id':'course-a','repository':'https://example.test/org/native.git','commit':'a'*40,'mount':'/course'}]}
        self.lock={'prairielearn':{'image':'docker.io/prairielearn/prairielearn@sha256:'+'b'*64},'javaGrader':{'localImage':'ghcr.io/example/java-grader:pilot-1','localImageId':'sha256:'+'c'*64}}
    def validate(self): return self.module.validate_registry(self.registry,self.lock)
    def reject(self):
        with self.assertRaises(self.module.RegistryError): self.validate()
    def test_valid_registry(self): self.assertEqual(self.validate(),self.registry['courses'])
    def test_duplicate_id(self):
        self.registry['courses'].append({**self.registry['courses'][0],'mount':'/course2'});self.reject()
    def test_duplicate_mount(self):
        self.registry['courses'].append({**self.registry['courses'][0],'id':'course-b'});self.reject()
    def test_moving_branch(self): self.registry['courses'][0]['commit']='main';self.reject()
    def test_credentials_or_non_https_url(self):
        for url in ['http://example.test/org/a','https://user:secret@example.test/a','https://example.test/a?token=x','https://example.test/a#x','file:///tmp/course','https://example.test/../course','https://example.test/a\\b']:
            with self.subTest(url=url):
                self.registry['courses'][0]['repository']=url;self.reject()
    def test_bad_mount(self):
        for mount in ['/course1','/course/../course2','/tmp/course','course','/course0']:
            with self.subTest(mount=mount):
                self.registry['courses'][0]['mount']=mount;self.reject()
    def test_invalid_id(self): self.registry['courses'][0]['id']='../escape';self.reject()
    def test_missing_image_pin(self): self.lock['prairielearn']['image']='prairielearn:latest';self.reject()
    def test_missing_local_grader_identity(self): self.lock['javaGrader'].pop('localImageId');self.reject()
    def test_nonobject_and_unknown_fields(self):
        for value in [None,[],{'schema':'pl-courses-v1','courses':[None]}, {**self.registry,'unexpected':True}]:
            with self.subTest(value=value):
                self.registry=value;self.reject()
