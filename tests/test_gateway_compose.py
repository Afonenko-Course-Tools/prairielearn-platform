"""Приватные mounts и runtime guards в compose без запуска Docker."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).parents[1]


class GatewayCompose(unittest.TestCase):
    def test_overlay_runs_private_bridge_without_delivery_mount(self):
        service = yaml.safe_load((ROOT / 'compose/compose.gateway.yml').read_text())['services']['pl']
        self.assertEqual(service['image'], '${PL_GATEWAY_IMAGE:?set the reviewed versioned derived bridge image}')
        self.assertEqual(service['command'], ['/PrairieLearn/scripts/start-gateway-bridge.sh'])
        self.assertNotIn('ports', service)
        self.assertEqual(service['environment']['NODE_ENV'], 'production')
        self.assertEqual(service['environment']['PL_GATEWAY_CONFIG'], '/run/pl-gateway/config.json')
        mounts = {target: (source, mode) for source, target, mode in (row.rsplit(':', 2) for row in service['volumes'])}
        self.assertEqual(set(mounts), {'/run/pl-gateway/config.json', '/run/secrets/pl-gateway-token'})
        self.assertTrue(all(mode == 'ro' for source, mode in mounts.values()))

    def test_production_native_course_stays_in_pl_and_is_not_exposed_to_gateway(self):
        services = yaml.safe_load((ROOT / 'compose/compose.prod.yml').read_text())['services']
        pl_mounts = {row['target']: row for row in services['pl']['volumes'] if isinstance(row, dict)}
        course = pl_mounts['/course']
        self.assertEqual(course['source'], '${COURSE_DIR:?Нужен проверенный native course}')
        self.assertTrue(course['read_only'])
        self.assertFalse(course['bind']['create_host_path'])
        gateway_mounts = {row['target']: row for row in services['gateway']['volumes']}
        self.assertEqual(set(gateway_mounts), {'/run/config', '/var/lib/gateway'})
        self.assertTrue(gateway_mounts['/run/config']['read_only'])
        self.assertFalse(gateway_mounts['/var/lib/gateway'].get('read_only', False))

    def test_production_preserves_native_module_paths_and_runtime_guards(self):
        services = yaml.safe_load((ROOT / 'compose/compose.prod.yml').read_text())['services']
        pl = services['pl']
        mounts = {row['target']: row for row in pl['volumes'] if isinstance(row, dict)}
        for name in ['sync-native-course.mjs', 'course-sync-policy.mjs', 'institution-bootstrap.mjs', 'bootstrap-native-course.mjs', 'native-course-payload.mjs']:
            self.assertTrue(mounts['/PrairieLearn/apps/prairielearn/tools/' + name]['read_only'])
        self.assertTrue(mounts['/PrairieLearn/apps/prairielearn/config/institutions.json']['read_only'])
        self.assertEqual(pl['environment']['NODE_ENV'], 'production')
        self.assertEqual(pl['environment']['PL_GATEWAY_CONFIG'], '/run/pl-gateway/config.json')
        self.assertEqual(pl['command'], ['/PrairieLearn/scripts/start-gateway-bridge.sh'])
        for name in ['pl', 'gateway']:
            self.assertNotIn('ports', services[name])
            self.assertEqual(services[name]['pull_policy'], 'never')
        gateway = services['gateway']
        self.assertEqual(gateway['depends_on']['pl']['condition'], 'service_healthy')
        self.assertTrue(gateway['read_only'])
        self.assertEqual(gateway['cap_drop'], ['ALL'])
        self.assertEqual(gateway['security_opt'], ['no-new-privileges:true'])
        self.assertEqual(services['proxy']['ports'], ['${PL_BIND_IP:?Нужен IP VM}:443:443'])
