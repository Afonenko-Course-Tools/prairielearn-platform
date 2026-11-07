"""Приватные mounts и runtime guards в compose без запуска Docker."""
import pathlib
import unittest
from selected_job_fixture import fixture_list, fixture_record, fixture_text
from typing import TypeGuard

import yaml

ROOT = pathlib.Path(__file__).parents[1]


def _mount_object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


class GatewayCompose(unittest.TestCase):
    def test_overlay_runs_private_bridge_without_delivery_mount(self) -> None:
        service = fixture_record(fixture_record(fixture_record(yaml.safe_load((ROOT / 'compose/compose.gateway.yml').read_text()))['services'])['pl'])
        self.assertEqual(service['image'], '${PL_GATEWAY_IMAGE:?set the reviewed versioned derived bridge image}')
        self.assertEqual(service['command'], ['/PrairieLearn/scripts/start-gateway-bridge.sh'])
        self.assertNotIn('ports', service)
        self.assertEqual(fixture_record(service['environment'])['NODE_ENV'], 'production')
        self.assertEqual(fixture_record(service['environment'])['PL_GATEWAY_CONFIG'], '/run/pl-gateway/config.json')
        mounts = {target: (source, mode) for source, target, mode in (fixture_text(row).rsplit(':', 2) for row in fixture_list(service['volumes']))}
        self.assertEqual(set(mounts), {'/run/pl-gateway/config.json', '/run/secrets/pl-gateway-token'})
        self.assertTrue(all(mode == 'ro' for _, mode in mounts.values()))

    def test_production_native_course_stays_in_pl_and_is_not_exposed_to_gateway(self) -> None:
        services = fixture_record(fixture_record(yaml.safe_load((ROOT / 'compose/compose.prod.yml').read_text()))['services'])
        pl_mounts = {fixture_text(fixture_record(row)['target']): fixture_record(row) for row in fixture_list(fixture_record(services['pl'])['volumes']) if _mount_object(row)}
        course = pl_mounts['/course']
        self.assertEqual(course['source'], '${COURSE_DIR:?Нужен проверенный native course}')
        self.assertTrue(course['read_only'])
        self.assertFalse(fixture_record(course['bind'])['create_host_path'])
        gateway_mounts = {fixture_text(fixture_record(row)['target']): fixture_record(row) for row in fixture_list(fixture_record(services['gateway'])['volumes'])}
        self.assertEqual(set(gateway_mounts), {'/run/config', '/var/lib/gateway'})
        self.assertTrue(gateway_mounts['/run/config']['read_only'])
        self.assertFalse(gateway_mounts['/var/lib/gateway'].get('read_only', False))

    def test_production_preserves_native_module_paths_and_runtime_guards(self) -> None:
        services = fixture_record(fixture_record(yaml.safe_load((ROOT / 'compose/compose.prod.yml').read_text()))['services'])
        pl = fixture_record(services['pl'])
        mounts = {fixture_text(fixture_record(row)['target']): fixture_record(row) for row in fixture_list(pl['volumes']) if _mount_object(row)}
        for name in ['sync-native-course.mjs', 'course-sync-policy.mjs', 'institution-bootstrap.mjs', 'bootstrap-native-course.mjs', 'native-course-payload.mjs']:
            self.assertTrue(mounts['/PrairieLearn/apps/prairielearn/tools/' + name]['read_only'])
        self.assertTrue(mounts['/PrairieLearn/apps/prairielearn/config/institutions.json']['read_only'])
        self.assertEqual(fixture_record(pl['environment'])['NODE_ENV'], 'production')
        self.assertEqual(fixture_record(pl['environment'])['PL_GATEWAY_CONFIG'], '/run/pl-gateway/config.json')
        self.assertEqual(pl['command'], ['/PrairieLearn/scripts/start-gateway-bridge.sh'])
        for name in ['pl', 'gateway']:
            self.assertNotIn('ports', fixture_record(services[name]))
            self.assertEqual(fixture_record(services[name])['pull_policy'], 'never')
        gateway = fixture_record(services['gateway'])
        self.assertEqual(fixture_record(fixture_record(gateway['depends_on'])['pl'])['condition'], 'service_healthy')
        self.assertTrue(gateway['read_only'])
        self.assertEqual(gateway['cap_drop'], ['ALL'])
        self.assertEqual(gateway['security_opt'], ['no-new-privileges:true'])
        self.assertEqual(fixture_record(services['proxy'])['ports'], ['${PL_BIND_IP:?Нужен IP VM}:443:443'])
