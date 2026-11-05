"""Описания публичных примеров не являются входом проверяющего раннера."""
import json
import unittest
from pathlib import Path
import jsonschema

import test_assertion_feedback as assertions
import test_grading_job as fixtures

ROOT = Path(__file__).resolve().parents[1]


class PublicTestBoundary(unittest.TestCase):
    def test_closed_schemas_do_not_offer_description_cards(self):
        for name in ('project-check', 'native-checks', 'grading-job-v3', 'grading-descriptor', 'check-result'):
            value = json.loads((ROOT / 'schemas' / (name + '.schema.json')).read_text())
            def properties(node):
                if isinstance(node, dict):
                    yield from node.get('properties', {})
                    for child in node.values():
                        yield from properties(child)
                elif isinstance(node, list):
                    for child in node:
                        yield from properties(child)
            with self.subTest(schema=name):
                self.assertNotIn('public-cases', list(properties(value)))
                self.assertNotIn('publicCases', list(properties(value)))
                self.assertNotIn('publicCaseObservations', list(properties(value)))

    def test_descriptor_schema_rejects_a_previously_valid_description(self):
        fixture = fixtures.JUnitJob(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = dict(fixture.cfg, publicCases=[{
            'id': 'normal', 'name': 'Обычный результат', 'test': 'AnswerTest#right',
            'input': '', 'expected': '42',
        }])
        schema = json.loads((ROOT / 'schemas/grading-descriptor.schema.json').read_text())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(config)

    def test_grader_rejects_removed_descriptor_field(self):
        fixture = fixtures.JUnitJob()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.cfg['publicCases'] = []
        with self.assertRaises(fixtures.grader.GraderError):
            fixtures.grader.validate_config(fixture.cfg)

    def test_legacy_observation_cannot_add_a_card_or_override_junit(self):
        counts = assertions.CheckShape().counts()
        leaf = counts['cases'][0]
        leaf['name'] = 'Обычный JUnit display name'
        source = {'classification': 'success', 'score': 1, 'counts': counts,
                  'publicCaseObservations': [{'id': 'legacy', 'test': 'T#t',
                                              'actual': 'CLOSED_LEGACY_VALUE', 'status': 'passed'}]}
        descriptor = {'publicCases': [{'id': 'legacy', 'test': 'T#t',
                                      'name': 'CLOSED_LEGACY_NAME', 'action': 'CLOSED_ACTION',
                                      'expected': 'CLOSED_EXPECTED'}]}
        native = assertions.feedback(source, descriptor)
        self.assertEqual(len(native['tests']), 1)
        self.assertEqual(native['tests'][0]['name'], leaf['name'])
        self.assertEqual(native['score'], 1)
        self.assertNotIn('publicCases', native['feedback'])
        self.assertNotIn('CLOSED_', json.dumps(native))
        self.assertIn('Ожидается: ' + leaf['checks'][0]['expected'], native['tests'][0]['message'])

    def test_no_description_cards_on_compile_or_infrastructure_failure(self):
        for kind in ('student-compilation-failure', 'infrastructure-failure'):
            native = assertions.feedback({'classification': kind, 'score': 0}, {})
            self.assertNotIn('publicCases', native['feedback'])
            self.assertFalse(native.get('tests'))
            if kind == 'infrastructure-failure':
                self.assertFalse(native['gradable'])
                self.assertNotIn('score', native)


class AuthorFeedbackBoundary(unittest.TestCase):
    def test_input_schemas_do_not_offer_author_feedback(self):
        for name in ('project-check', 'native-checks', 'grading-job-v3', 'grading-descriptor'):
            schema = json.loads((ROOT / 'schemas' / (name + '.schema.json')).read_text())
            def offered(node):
                if isinstance(node, dict):
                    yield from node.get('properties', {})
                    for child in node.values():
                        yield from offered(child)
                elif isinstance(node, list):
                    for child in node:
                        yield from offered(child)
            with self.subTest(schema=name):
                self.assertNotIn('feedback', list(offered(schema)))

    def test_author_feedback_is_rejected_by_schema_and_grader(self):
        fixture = fixtures.JUnitJob(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = dict(fixture.cfg, feedback={'requirement': 'Требование', 'whatCheck': 'Пояснение'})
        schema = json.loads((ROOT / 'schemas/grading-descriptor.schema.json').read_text())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(config)
        with self.assertRaises(fixtures.grader.GraderError):
            fixtures.grader.validate_config(config)

    def test_removed_author_feedback_cannot_enrich_native_output(self):
        descriptor = {'feedback': {'requirement': 'CLOSED_REQUIREMENT', 'whatCheck': 'CLOSED_HINT'}}
        for classification in ('success', 'behavior-failure', 'infrastructure-failure', 'student-compilation-failure'):
            source = {'classification': classification, 'score': 0}
            with self.subTest(classification=classification):
                expected = assertions.feedback(source, {})
                actual = assertions.feedback(source, descriptor)
                self.assertEqual(actual, expected)
                self.assertIn('feedback', actual)
                self.assertNotIn('CLOSED_', json.dumps(actual))

    def test_ordinary_junit_projection_survives_removed_author_feedback(self):
        source = {'classification': 'behavior-failure', 'score': 0,
                  'counts': assertions.CheckShape().counts()}
        actual = assertions.feedback(source, {'feedback': {'requirement': 'CLOSED_REQUIREMENT', 'whatCheck': 'CLOSED_HINT'}})
        self.assertEqual(actual, assertions.feedback(source, {}))
        self.assertEqual(actual['feedback']['cases'][0]['checks'], source['counts']['cases'][0]['checks'])
        self.assertEqual(len(actual['tests']), 1)


if __name__ == '__main__':
    unittest.main()
