import json,pathlib,subprocess,tempfile,os,unittest
class GatewayCompose(unittest.TestCase):
    def test_overlay_runs_explicit_derived_image_and_bridge_wrapper(self):
        root=pathlib.Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'HOST_JOBS_DIR':directory,'PL_GATEWAY_IMAGE':'codex-release-community-bridge:1.0.0-candidate','PL_GATEWAY_CONFIG_PATH':directory+'/config.json','PL_GATEWAY_TOKEN_PATH':directory+'/token','PL_GATEWAY_DELIVERY_PATH':directory+'/native'}
            proc=subprocess.run(['docker','compose','-p','codex-bridge-config-test','-f',str(root/'compose/compose.yml'),'-f',str(root/'compose/compose.gateway.yml'),'config','--format','json'],env=env,capture_output=True,text=True,check=True)
            service=json.loads(proc.stdout)['services']['pl']
            self.assertEqual(service['image'],env['PL_GATEWAY_IMAGE'])
            self.assertEqual(service['command'],['/PrairieLearn/scripts/start-gateway-bridge.sh'])
            self.assertNotIn('ports',service)
            self.assertEqual(service['environment']['NODE_ENV'],'production')

    def test_production_operator_mounts_match_native_module_import_paths(self):
        root=pathlib.Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'PL_IMAGE':'synthetic/pl:1','GATEWAY_IMAGE':'synthetic/gateway:1','NGINX_IMAGE':'synthetic/nginx:1','HOST_JOBS_DIR':directory,'PL_PRIVATE':directory,'COURSE_DIR':directory,'GATEWAY_PRIVATE':directory,'GATEWAY_DATA':directory,'PL_BIND_IP':'127.0.0.1','NGINX_CONFIG':directory+'/nginx.conf','PROXY_PRIVATE':directory,'TLS_DIR':directory}
            proc=subprocess.run(['docker','compose','-f',str(root/'compose/compose.prod.yml'),'config','--format','json'],env=env,capture_output=True,text=True,check=True)
            mounts={v['target']:v for v in json.loads(proc.stdout)['services']['pl']['volumes']}
            for name in ['sync-native-course.mjs','course-sync-policy.mjs','institution-bootstrap.mjs','bootstrap-native-course.mjs','native-course-payload.mjs']:
                target='/PrairieLearn/apps/prairielearn/tools/'+name
                self.assertIn(target,mounts)
                self.assertTrue(mounts[target]['read_only'])
            self.assertIn('/PrairieLearn/apps/prairielearn/config/institutions.json',mounts)
            self.assertTrue(mounts['/PrairieLearn/apps/prairielearn/config/institutions.json']['read_only'])
