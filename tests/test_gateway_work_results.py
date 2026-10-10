import json,os,pathlib,urllib.request,urllib.error,urllib.parse,unittest
import jsonschema
@unittest.skipUnless(os.environ.get('PL_GATEWAY_LAB_FIXTURE'),'ordinary lab fixture not configured')
class OrdinaryLabResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.f=json.loads(pathlib.Path(os.environ['PL_GATEWAY_LAB_FIXTURE']).read_text())
    def read(self,**overrides):
        query={**self.f['query'],**overrides}
        token=pathlib.Path(self.f['tokenFile']).read_text().strip()
        req=urllib.request.Request(self.f['bridgeUrl']+'/internal/gateway/work-results?'+urllib.parse.urlencode(query),headers={'Authorization':'Bearer '+token})
        try:r=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,json.load(r)
    def test_current_enrolled_lab_read_without_defense_slot(self):
        status,result=self.read();self.assertEqual(status,200)
        schema=json.loads((pathlib.Path(__file__).parents[1]/'schemas/gateway-work-results.schema.json').read_text())
        jsonschema.validate(result,schema)
        for key in ('userUid','instance','deliveryHash','workId'):self.assertEqual(result[key],self.f['query'][key])
        self.assertNotIn('assignmentId',result);self.assertNotIn('version',result)
    def test_missing_enrollment_denied(self):self.assertEqual(self.read(userUid=self.f['unenrolledUid'])[0],403)
    def test_foreign_work_denied(self):self.assertEqual(self.read(workId='foreign-work')[0],403)
    def test_foreign_delivery_denied(self):self.assertEqual(self.read(deliveryHash='0'*64)[0],403)
    def test_defense_cannot_bypass_assignment_via_lab_endpoint(self):self.assertEqual(self.read(workId='defense-a')[0],403)
    def test_query_cannot_supply_staff_role(self):self.assertEqual(self.read(role='Administrator')[0],400)
    def test_unattempted_does_not_invent_grade(self):
        status,result=self.read(userUid=self.f['unattemptedUid']);self.assertEqual(status,200)
        self.assertIsNone(result['currentAttempt']);self.assertIsNone(result['scoreGiven']);self.assertIsNone(result['scoreMaximum'])

    def launch(self,**overrides):
        query={**self.f['query'],**overrides};token=pathlib.Path(self.f['tokenFile']).read_text().strip()
        req=urllib.request.Request(self.f['bridgeUrl']+'/internal/gateway/work-launch?'+urllib.parse.urlencode(query),headers={'Authorization':'Bearer '+token})
        try:r=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,json.load(r)
    def test_launch_path_is_native_and_scoped(self):
        status,result=self.launch();self.assertEqual(status,200)
        schema=json.loads((pathlib.Path(__file__).parents[1]/'schemas/gateway-work-launch.schema.json').read_text());jsonschema.validate(result,schema)
        self.assertEqual(result['workId'],self.f['query']['workId']);self.assertEqual(result['path'],self.f['expectedLaunchPath'])
    def test_unassigned_defense_launch_denied(self):self.assertEqual(self.launch(workId='defense-a')[0],403)
    def test_unenrolled_launch_denied(self):self.assertEqual(self.launch(userUid=self.f['unenrolledUid'])[0],403)
    def test_launch_cannot_supply_native_id_or_path(self):self.assertEqual(self.launch(assessmentId='1',path='/pl/administrator')[0],400)

    def enroll(self,**overrides):
        body={k:self.f['query'][k] for k in ('userUid','instance','deliveryHash')};body.update(overrides)
        token=pathlib.Path(self.f['tokenFile']).read_text().strip()
        req=urllib.request.Request(self.f['bridgeUrl']+'/internal/gateway/enrollment',method='PUT',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:r=urllib.request.urlopen(req,timeout=20)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,json.load(r)
    def test_basic_enrollment_is_idempotent_and_has_no_assignment_grant(self):
        for _ in range(2):
            status,result=self.enroll(userUid=self.f['bootstrapUid']);self.assertEqual(status,200)
            self.assertEqual(set(result),{'schemaVersion','userUid','instance','deliveryHash','enrolled'});self.assertTrue(result['enrolled'])
    def test_basic_enrollment_cannot_supply_role_or_labels(self):self.assertEqual(self.enroll(role='Administrator',labels=['defense-a'])[0],400)
    def test_enrollment_requires_existing_community_identity(self):self.assertEqual(self.enroll(userUid='unverified-user-does-not-exist')[0],404)

    def test_native_student_resolver_denies_closed_ordinary_lab(self):
        self.assertEqual(self.read(workId='closed-lab')[0],403)
        self.assertEqual(self.launch(workId='closed-lab')[0],403)
    def test_native_weighted_grade_preserved(self):
        status,result=self.read();self.assertEqual(status,200)
        self.assertEqual((result['scoreGiven'],result['scoreMaximum']),(6,8))
        self.assertNotEqual(result['scoreGiven']/result['scoreMaximum'],sum(q['score'] for q in result['questions'])/len(result['questions']))

    def test_assigned_defense_launch_uses_current_native_journal(self):
        status,result=self.launch(**self.f['assignedDefenseQuery']);self.assertEqual(status,200)
        self.assertEqual(result['path'],'/pl/course_instance/1/assessment/2/')
        self.assertEqual(self.launch(**{**self.f['assignedDefenseQuery'],'workId':'defense-a'})[0],403)

    def test_blocked_native_enrollment_cannot_be_reopened_by_bootstrap(self):
        self.assertEqual(self.enroll(userUid='bridge-spike-g')[0],403)
        self.assertEqual(self.read(userUid='bridge-spike-g')[0],403)
