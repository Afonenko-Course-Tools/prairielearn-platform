from pathlib import Path
import unittest
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'tools/check_registry.py'
sys.path.insert(0, str(SCRIPT.parent))
import check_registry as registry_module
from check_registry import Course

class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(),'Registry validator is not implemented')
        self.module = registry_module
        self.courses: list[dict[str, str]] = [{'id':'course-a','repository':'https://example.test/org/native.git','commit':'a'*40,'mount':'/course'}]
        self.registry: dict[str, object] = {'schema':'pl-courses-v1','courses':self.courses}
        self.lock={'prairielearn':{'image':'docker.io/prairielearn/prairielearn@sha256:'+'b'*64},'javaGrader':{'localImage':'ghcr.io/example/java-grader:pilot-1','localImageId':'sha256:'+'c'*64}}
    def validate(self) -> list[Course]: return self.module.validate_registry(self.registry,self.lock)
    def reject(self) -> None:
        with self.assertRaises(self.module.RegistryError): self.validate()
    def test_valid_registry(self) -> None: self.assertEqual(self.validate(),self.courses)
    def test_duplicate_id(self) -> None:
        self.courses.append({**self.courses[0],'mount':'/course2'});self.reject()
    def test_duplicate_mount(self) -> None:
        self.courses.append({**self.courses[0],'id':'course-b'});self.reject()
    def test_moving_branch(self) -> None: self.courses[0]['commit']='main';self.reject()
    def test_credentials_or_non_https_url(self) -> None:
        for url in ['http://example.test/org/a','https://user:secret@example.test/a','https://example.test/a?token=x','https://example.test/a#x','file:///tmp/course','https://example.test/../course','https://example.test/a\\b']:
            with self.subTest(url=url):
                self.courses[0]['repository']=url;self.reject()
    def test_bad_mount(self) -> None:
        for mount in ['/course1','/course/../course2','/tmp/course','course','/course0']:
            with self.subTest(mount=mount):
                self.courses[0]['mount']=mount;self.reject()
    def test_invalid_id(self) -> None: self.courses[0]['id']='../escape';self.reject()
    def test_missing_image_pin(self) -> None: self.lock['prairielearn']['image']='prairielearn:latest';self.reject()
    def test_missing_local_grader_identity(self) -> None: self.lock['javaGrader'].pop('localImageId');self.reject()
    def test_nonobject_and_unknown_fields(self) -> None:
        invalid: list[object] = [None, [], {'schema':'pl-courses-v1','courses':[None]}, {**self.registry,'unexpected':True}]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(self.module.RegistryError):
                    self.module.validate_registry(value, self.lock)

class InstitutionRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = registry_module
        self.assertTrue(hasattr(self.module,'validate_institutions'),'Institution catalog validation is missing')
        self.institutions: dict[str, dict[str, str | None]] = {'synthetic':{'shortName':'SYN','longName':'Synthetic University','displayTimezone':'Europe/Minsk','uidRegexp':None}}
        self.catalog: dict[str, object] = {'schema':'pl-institutions-v1','institutions':self.institutions}
        self.courses: list[dict[str, str]] = [{'id':'course-a','institution':'synthetic','repository':'https://example.test/org/native.git','commit':'a'*40,'mount':'/course'}]
        self.registry: dict[str, object] = {'schema':'pl-courses-v2','courses':self.courses}
        self.lock={'prairielearn':{'image':'example@sha256:'+'b'*64},'javaGrader':{'localImage':'example:1','localImageId':'sha256:'+'c'*64}}
    def validate(self) -> list[Course]:return self.module.validate_registry(self.registry,self.lock,self.catalog)
    def test_generic_descriptor_reference(self) -> None:
        self.assertEqual(self.validate(),self.courses)
    def test_unknown_institution_rejected(self) -> None:
        self.courses[0]['institution']='unknown'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_missing_institution_rejected(self) -> None:
        del self.courses[0]['institution']
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_native_database_id_is_not_a_descriptor(self) -> None:
        self.institutions['synthetic']['id']='42'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_duplicate_native_short_name_rejected(self) -> None:
        self.institutions['other']=dict(self.institutions['synthetic'])
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_bad_timezone_rejected(self) -> None:
        self.institutions['synthetic']['displayTimezone']='Not/AZone'
        with self.assertRaises(self.module.RegistryError):self.validate()
    def test_versioned_bsu_descriptor_validates(self) -> None:
        import json
        catalog=json.loads((SCRIPT.parents[1]/'config/institutions.json').read_text())
        self.assertEqual(self.module.validate_institutions(catalog)['bsu']['shortName'],'БГУ')
