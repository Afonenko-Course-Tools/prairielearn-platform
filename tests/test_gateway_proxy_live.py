"""Read-only ordinary Student ACL/results checks using real issued cookie jars."""
import json,os,pathlib,urllib.request,urllib.error,unittest
import jsonschema

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
    def test_students_see_assigned_defense_and_not_foreign(self):
        for student in self.fixture['students']:
            with self.subTest(student=student['assignmentId']):
                status,body=self.native(student,self.fixture['listPath'])
                self.assertEqual(status,200)
                self.assertIn(student['ownWork'],body)
                self.assertNotIn(student['foreignWork'],body)
    def test_foreign_defense_direct_url_denied_in_existing_session(self):
        for student in self.fixture['students']:
            with self.subTest(student=student['assignmentId']):
                self.assertIn(self.native(student,student['foreignPath'])[0],(403,404))
                self.assertIn(self.native(student,student['ownPath'])[0],(200,302))
    def test_results_are_schema_valid_and_bound_to_current_student(self):
        token=pathlib.Path(self.fixture['tokenFile']).read_text().strip()
        schema=json.loads((pathlib.Path(__file__).parents[1]/'schemas/gateway-results.schema.json').read_text())
        for student in self.fixture['students']:
            path=f"/internal/gateway/results?assignmentId={student['assignmentId']}&version={student['version']}"
            req=urllib.request.Request(self.fixture['bridgeUrl']+path,headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req,timeout=20) as r:result=json.load(r)
            jsonschema.validate(result,schema)
            self.assertEqual(result['userUid'],student['userUid'])
            self.assertEqual(result['workId'],student['ownWork'])
            self.assertEqual(result['deliveryHash'],self.fixture['deliveryHash'])
            self.assertEqual(result['version'],student['version'])
