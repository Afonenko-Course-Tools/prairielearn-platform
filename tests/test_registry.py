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

class InstitutionRegistryTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('registry',SCRIPT)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.assertTrue(hasattr(self.module,'validate_institutions'),'Institution catalog validation is missing')
        self.catalog={'schema':'pl-institutions-v1','institutions':{'synthetic':{'shortName':'SYN','longName':'Synthetic University','displayTimezone':'Europe/Minsk','uidRegexp':None}}}
        self.registry={'schema':'pl-courses-v2','courses':[{'id':'course-a','institution':'synthetic','repository':'https://example.test/org/native.git','commit':'a'*40,'mount':'/course'}]}
        self.lock={'prairielearn':{'image':'example@sha256:'+'b'*64},'javaGrader':{'localImage':'example:1','localImageId':'sha256:'+'c'*64}}
    def validate(self):return self.module.validate_registry(self.registry,self.lock,self.catalog)
    def test_generic_descriptor_reference(self):
        self.assertEqual(self.validate(),self.registry['courses'])
    def test_unknown_institution_rejected(self):
        self.registry['courses'][0]['institution']='unknown'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_missing_institution_rejected(self):
        del self.registry['courses'][0]['institution']
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_native_database_id_is_not_a_descriptor(self):
        self.catalog['institutions']['synthetic']['id']='42'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_duplicate_native_short_name_rejected(self):
        self.catalog['institutions']['other']=dict(self.catalog['institutions']['synthetic'])
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_bad_timezone_rejected(self):
        self.catalog['institutions']['synthetic']['displayTimezone']='Not/AZone'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_versioned_bsu_descriptor_validates(self):
        import json
        catalog=json.loads((SCRIPT.parents[1]/'config/institutions.json').read_text())
        self.assertEqual(self.module.validate_institutions(catalog)['bsu']['shortName'],'БГУ')
