"""Проверки native Student ACL с уже выданными cookie; без Bridge results API."""
import json,os,pathlib,urllib.request,urllib.error,unittest

@unittest.skipUnless(os.environ.get('PL_GATEWAY_STUDENT_FIXTURE'),'verified Student fixture not configured')
class OrdinaryStudentAcl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(pathlib.Path(os.environ['PL_GATEWAY_STUDENT_FIXTURE']).read_text())
    def native(self,student,path):
        cookies=json.loads(pathlib.Path(student['cookieFile']).read_text())
        cookie='; '.join(c['name']+'='+c['value'] for c in cookies if c['name'] in ('prairielearn_session','pl2_session'))
        req=urllib.request.Request(self.fixture['privateNativeUrl']+path,headers={'Cookie':cookie,'Host':self.fixture['host'],'X-Forwarded-Proto':'https'})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        try:r=urllib.request.build_opener(NoRedirect).open(req,timeout=20)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,r.read().decode()
    def test_native_student_list_exposes_only_accessible_work(self):
        for student in self.fixture['students']:
            with self.subTest(student=student['userUid']):
                status,body=self.native(student,self.fixture['listPath'])
                self.assertEqual(status,200)
                self.assertIn(student['ownWork'],body)
                self.assertNotIn(student['foreignWork'],body)
    def test_native_direct_url_enforces_access_in_existing_student_session(self):
        for student in self.fixture['students']:
            with self.subTest(student=student['userUid']):
                self.assertIn(self.native(student,student['foreignPath'])[0],(403,404))
                self.assertIn(self.native(student,student['ownPath'])[0],(200,302))
