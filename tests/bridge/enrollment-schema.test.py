"""Закрытый wire-контракт приватного native зачисления."""
import json
import pathlib
import unittest
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[2]
REQUEST = {'userUid': 'student@fixture.invalid', 'instance': 'fall', 'courseKey': 'demo', 'role': 'student', 'email': None}


class EnrollmentSchema(unittest.TestCase):
    def test_request_accepts_only_native_role_and_canonical_nullable_email(self):
        validator = Draft202012Validator(json.loads((ROOT / 'schemas/gateway-enrollment.schema.json').read_text()))
        for email in [None, 'owner@fixture.invalid', 'owner+alias@fixture.invalid']:
            self.assertTrue(validator.is_valid({**REQUEST, 'email': email}))
        for change in [{'email': 'OWNER@fixture.invalid'}, {'email': 'owner@localhost'}, {'email': 'owner..name@fixture.invalid'}, {'email': 'owner@fixture.invalid\n'}, {'email': 'x'*65+'@fixture.invalid'}, {'email': 'owner@'+'x'*64+'.invalid'}, {'email': 'ownér@fixture.invalid'}, {'role': 'administrator'}, {'userUid': ''}, {'instance': ''}, {'courseKey': 'DEMO'}, {'path': '/pl/'}]:
            self.assertFalse(validator.is_valid({**REQUEST, **change}), change)
        for field in REQUEST:
            self.assertFalse(validator.is_valid({key: value for key, value in REQUEST.items() if key != field}), field)

    def test_response_has_only_safe_native_assessments_path(self):
        validator = Draft202012Validator(json.loads((ROOT / 'schemas/gateway-enrollment-response.schema.json').read_text()))
        response = {'schemaVersion': 1, 'userUid': REQUEST['userUid'], 'instance': 'fall', 'courseKey': 'demo', 'enrolled': True, 'path': '/pl/course_instance/73/assessments'}
        self.assertTrue(validator.is_valid(response))
        for path in ['/pl/course_instance/0/assessments', '/pl/course_instance/73/assessments?x=1', '/pl/course_instance/73/assessments/', 'https://fixture.invalid/pl/course_instance/73/assessments', '/pl/course_instance/73/assessments\n']:
            self.assertFalse(validator.is_valid({**response, 'path': path}), path)
        self.assertFalse(validator.is_valid({**response, 'email': None}))


if __name__ == '__main__':
    unittest.main()
