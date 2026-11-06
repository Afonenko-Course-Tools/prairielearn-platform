"""Ожидаемая ошибка исполнения заготовки проходит штатную подготовку Job."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import test_selected_file_delivery as fixtures

g = fixtures.g


class RuntimeExpectations(unittest.TestCase):
    def test_runtime_failure_starter_reaches_prepared_job(self):
        manifest = fixtures.manifest()
        manifest['projects'][0]['check']['verification-expectations'] = {
            'starter': {'classification': 'student-runtime-failure'},
        }
        with tempfile.TemporaryDirectory() as snapshot:
            try:
                scenarios = g.scenario_inventory(manifest, Path(snapshot))
            except g.JobError:
                self.fail('Штатный inventory отверг существующую классификацию student-runtime-failure')
            self.assertEqual([entry['scenario'] for entry in scenarios], ['starter'])
            job = g.prepare_job(manifest, Path(snapshot), 'demo/exr-answer', 'starter',
                                registry=fixtures.registry())
            try:
                self.assertEqual(job['expectations']['classification'], 'student-runtime-failure')
            finally:
                shutil.rmtree(job.root)

    def test_author_expectations_accept_runtime_failure(self):
        for scenario in ('reference', 'starter'):
            with self.subTest(scenario=scenario):
                check = copy.deepcopy(fixtures.manifest()['projects'][0]['check'])
                check['verification-expectations'] = {
                    scenario: {'classification': 'student-runtime-failure'},
                }
                try:
                    g.validate('project-check', check)
                except g.JobError:
                    self.fail('Авторская схема отвергла существующую классификацию student-runtime-failure')

    def test_unknown_classification_remains_rejected(self):
        for scenario in ('reference', 'starter'):
            for schema in ('project-check', 'native-checks'):
                with self.subTest(scenario=scenario, schema=schema):
                    manifest = fixtures.manifest()
                    check = manifest['projects'][0]['check']
                    check['verification-expectations'] = {
                        scenario: {'classification': 'unknown-runtime-outcome'},
                    }
                    with self.assertRaises(g.JobError):
                        g.validate(schema, check if schema == 'project-check' else manifest)


if __name__ == '__main__':
    unittest.main()
