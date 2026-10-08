"""Opt-in HTTPS tests against the isolated synthetic proxy upstream."""
import http.client
import json
import os
from pathlib import Path
import ssl
import unittest

@unittest.skipUnless(os.environ.get('PL_PROXY_TEST_CA'),'Start compose.proxy-test.yml and set PL_PROXY_TEST_CA')
class ProxyIntegration(unittest.TestCase):
    def request(self,path,headers=None):
        context=ssl.create_default_context(cafile=os.environ['PL_PROXY_TEST_CA'])
        conn=http.client.HTTPSConnection('localhost',int(os.environ.get('PL_PROXY_TEST_PORT','18443')),context=context,timeout=5)
        self.addCleanup(conn.close);conn.request('GET',path,headers=headers or {});return conn.getresponse()
    def test_native_path_and_query_are_preserved(self):
        response=self.request('/pl/example?x=1');self.assertEqual(response.status,200);self.assertEqual(json.loads(response.read())['path'],'/pl/example?x=1')
    def test_client_identity_and_forwarding_headers_are_stripped(self):
        response=self.request('/pl/example',{'X-Trust-Auth-Uid':'forged@example.test','X-Trust-Auth-Name':'Forged','X-Trust-Auth-Uin':'fake','X-Forwarded-For':'1.2.3.4','X-Forwarded-Proto':'http','Forwarded':'for=1.2.3.4'})
        headers={k.lower():v for k,v in json.loads(response.read())['headers'].items()}
        for name in ['x-trust-auth-uid','x-trust-auth-name','x-trust-auth-uin','forwarded']:self.assertNotIn(name,headers)
        self.assertNotEqual(headers['x-forwarded-for'],'1.2.3.4');self.assertEqual(headers['x-forwarded-proto'],'https')
    def test_auth_routes_fail_closed(self):
        for path in ['/pl/shibcallback','/pl/shibcallback?ticket=forged','/pl/shibcallback/extra','/gateway','/gateway/launch']:
            with self.subTest(path=path):self.assertEqual(self.request(path).status,503)
    def test_websocket_upgrade_reaches_upstream(self):
        response=self.request('/socket.io/?EIO=4&transport=websocket',{'Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Key':'dGhlIHNhbXBsZSBub25jZQ==','Sec-WebSocket-Version':'13'})
        self.assertEqual(response.status,101);self.assertEqual(response.getheader('Sec-WebSocket-Accept'),'s3pPLMBiTxaQ9kYGzzhZRbK+xOo=')
    def test_unknown_route_is_not_proxied(self):self.assertEqual(self.request('/unexpected').status,404)
