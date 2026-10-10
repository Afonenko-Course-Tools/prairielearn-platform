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
