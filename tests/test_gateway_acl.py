"""Private listener tests; live keys and identities are supplied outside Git."""
import json,os,pathlib,unittest,urllib.request,urllib.error

@unittest.skipUnless(os.environ.get('PL_GATEWAY_BRIDGE_URL'),'private Community bridge not configured')
class GatewayBridgeLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url=os.environ['PL_GATEWAY_BRIDGE_URL']
        cls.token=pathlib.Path(os.environ['PL_GATEWAY_TOKEN_FILE']).read_text().strip()
        cls.delivery=json.loads(pathlib.Path(os.environ['PL_GATEWAY_DELIVERY']).read_text())
    def request(self,path,method='GET',body=None,token=True):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+self.token
        req=urllib.request.Request(self.url+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=20) as r: return r.status,json.load(r)
        except urllib.error.HTTPError as e:
            with e: return e.code,json.load(e)
    def assignment(self,**overrides):
        return {'version':1,'userUid':'not-an-existing-verified-user','instance':'pilot','deliveryHash':self.delivery['deliveryHash'],'oldWork':None,'newWork':self.delivery['instances']['pilot']['works'][0],**overrides}
    def test_service_auth_required(self):
        self.assertEqual(self.request('/internal/gateway/results?assignmentId=test&version=1',token=False)[0],401)
    def test_browser_identity_headers_do_not_authenticate(self):
        req=urllib.request.Request(self.url+'/internal/gateway/results?assignmentId=test&version=1',headers={'X-Trusted-Uid':'student','Remote-User':'student'})
        with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code,401)
        caught.exception.close()
    def test_teacher_role_cannot_be_supplied_to_bridge(self):
        self.assertEqual(self.request('/internal/gateway/assignments/unknown','PUT',self.assignment(role='Administrator'))[0],400)
    def test_labels_cannot_be_supplied(self):
        self.assertEqual(self.request('/internal/gateway/assignments/unknown','PUT',self.assignment(labelId='1'))[0],400)
    def test_unknown_verified_identity_denied(self):
        self.assertEqual(self.request('/internal/gateway/assignments/unknown','PUT',self.assignment())[0],404)
    def test_foreign_delivery_denied(self):
        self.assertEqual(self.request('/internal/gateway/assignments/unknown','PUT',self.assignment(deliveryHash='0'*64))[0],403)
    def test_foreign_assessment_denied(self):
        self.assertEqual(self.request('/internal/gateway/assignments/unknown','PUT',self.assignment(newWork='not-in-manifest'))[0],409)
    def test_unknown_assignment_has_no_results(self):
        self.assertEqual(self.request('/internal/gateway/results?assignmentId=unknown&version=1')[0],409)
    def test_result_query_cannot_select_user_or_raw_assessment(self):
        self.assertEqual(self.request('/internal/gateway/results?assignmentId=unknown&version=1&userId=1')[0],400)

    @unittest.skipUnless(os.environ.get('PL_GATEWAY_TEST_EXISTING_UID'),'assigned synthetic identity not configured')
    def test_second_assignment_id_cannot_take_existing_slot(self):
        body=self.assignment(userUid=os.environ['PL_GATEWAY_TEST_EXISTING_UID'])
        self.assertEqual(self.request('/internal/gateway/assignments/other-slot','PUT',body)[0],409)
