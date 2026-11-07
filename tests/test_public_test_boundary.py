"""Описания публичных примеров не являются входом проверяющего раннера."""
import json
from collections.abc import Iterator
from typing import Protocol, runtime_checkable
from selected_job_fixture import fixture_record, fixture_list
import unittest
from pathlib import Path
import jsonschema

import test_assertion_feedback as assertions
from json_boundary import is_object, is_list
import test_grading_job as fixtures

ROOT = Path(__file__).resolve().parents[1]


@runtime_checkable
class SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


def schema_validator(value: object) -> SchemaValidator:
    if not isinstance(value, SchemaValidator):
        raise AssertionError('Контракт JSON Schema validator недоступен')
    return value


@runtime_checkable
class ConfigValidator(Protocol):
    def __call__(self, config: object) -> None: ...


def validate_config(config: object) -> None:
    validator: object = getattr(fixtures.grader, 'validate_config')
    if not isinstance(validator, ConfigValidator):
        raise AssertionError('Частный контракт validate_config недоступен')
    validator(config)



class PublicTestBoundary(unittest.TestCase):
    def test_closed_schemas_do_not_offer_description_cards(self) -> None:
        for name in ('project-check', 'native-checks', 'grading-job-v3', 'grading-descriptor', 'check-result'):
            value: object = json.loads((ROOT / 'schemas' / (name + '.schema.json')).read_text())
            def properties(node: object) -> Iterator[object]:
                if is_object(node):
                    declared = node.get('properties', {})
                    if is_object(declared):
                        yield from declared
                    for child in node.values():
                        yield from properties(child)
                elif is_list(node):
                    for child in node:
                        yield from properties(child)
            with self.subTest(schema=name):
                self.assertNotIn('public-cases', list(properties(value)))
                self.assertNotIn('publicCases', list(properties(value)))
                self.assertNotIn('publicCaseObservations', list(properties(value)))

    def test_descriptor_schema_rejects_a_previously_valid_description(self) -> None:
        fixture = fixtures.JUnitJob(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = dict(fixture.cfg, publicCases=[{
            'id': 'normal', 'name': 'Обычный результат', 'test': 'AnswerTest#right',
            'input': '', 'expected': '42',
        }])
        schema = json.loads((ROOT / 'schemas/grading-descriptor.schema.json').read_text())
        with self.assertRaises(jsonschema.ValidationError):
            validator = schema_validator(jsonschema.Draft202012Validator(schema))
            validator.validate(config)

    def test_grader_rejects_removed_descriptor_field(self) -> None:
        fixture = fixtures.JUnitJob()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture_record(fixture.cfg)['publicCases'] = []
        with self.assertRaises(fixtures.grader.GraderError):
            validate_config(fixture.cfg)

    def test_legacy_observation_cannot_add_a_card_or_override_junit(self) -> None:
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
        assert 'tests' in native
        self.assertEqual(len(native['tests']), 1)
        self.assertEqual(native['tests'][0]['name'], leaf['name'])
        assert 'score' in native
        self.assertEqual(native['score'], 1)
        self.assertNotIn('publicCases', native['feedback'])
        self.assertNotIn('CLOSED_', json.dumps(native))
        assert 'checks' in leaf
        self.assertIn('Ожидается: ' + leaf['checks'][0]['expected'], native['tests'][0]['message'])

    def test_no_description_cards_on_compile_or_infrastructure_failure(self) -> None:
        for kind in ('student-compilation-failure', 'infrastructure-failure'):
            native = assertions.feedback({'classification': kind, 'score': 0}, {})
            self.assertNotIn('publicCases', native['feedback'])
            self.assertFalse(native.get('tests'))
            if kind == 'infrastructure-failure':
                self.assertFalse(native['gradable'])
                self.assertNotIn('score', native)


class AuthorFeedbackBoundary(unittest.TestCase):
    def test_input_schemas_do_not_offer_author_feedback(self) -> None:
        for name in ('project-check', 'native-checks', 'grading-job-v3', 'grading-descriptor'):
            schema: object = json.loads((ROOT / 'schemas' / (name + '.schema.json')).read_text())
            def offered(node: object) -> Iterator[object]:
                if is_object(node):
                    declared = node.get('properties', {})
                    if is_object(declared):
                        yield from declared
                    for child in node.values():
                        yield from offered(child)
                elif is_list(node):
                    for child in node:
                        yield from offered(child)
            with self.subTest(schema=name):
                self.assertNotIn('feedback', list(offered(schema)))

    def test_author_feedback_is_rejected_by_schema_and_grader(self) -> None:
        fixture = fixtures.JUnitJob(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = dict(fixture.cfg, feedback={'requirement': 'Требование', 'whatCheck': 'Пояснение'})
        schema = json.loads((ROOT / 'schemas/grading-descriptor.schema.json').read_text())
        with self.assertRaises(jsonschema.ValidationError):
            validator = schema_validator(jsonschema.Draft202012Validator(schema))
            validator.validate(config)
        with self.assertRaises(fixtures.grader.GraderError):
            validate_config(config)

    def test_removed_author_feedback_cannot_enrich_native_output(self) -> None:
        descriptor = {'feedback': {'requirement': 'CLOSED_REQUIREMENT', 'whatCheck': 'CLOSED_HINT'}}
        for classification in ('success', 'behavior-failure', 'infrastructure-failure', 'student-compilation-failure'):
            source = {'classification': classification, 'score': 0}
            with self.subTest(classification=classification):
                expected = assertions.feedback(source, {})
                actual = assertions.feedback(source, descriptor)
                self.assertEqual(actual, expected)
                self.assertIn('feedback', actual)
                self.assertNotIn('CLOSED_', json.dumps(actual))

    def test_ordinary_junit_projection_survives_removed_author_feedback(self) -> None:
        source: dict[str, object] = {'classification': 'behavior-failure', 'score': 0,
                  'counts': assertions.CheckShape().counts()}
        actual = assertions.feedback(source, {'feedback': {'requirement': 'CLOSED_REQUIREMENT', 'whatCheck': 'CLOSED_HINT'}})
        self.assertEqual(actual, assertions.feedback(source, {}))
        assert 'cases' in actual['feedback']
        public_leaf = actual['feedback']['cases'][0]
        assert 'checks' in public_leaf
        counts = fixture_record(source['counts'])
        original_leaf = fixture_record(fixture_list(counts['cases'])[0])
        self.assertEqual(public_leaf['checks'], original_leaf['checks'])
        assert 'tests' in actual
        self.assertEqual(len(actual['tests']), 1)


if __name__ == '__main__':
    unittest.main()
