"""Схема принимает достаточную диагностику публичного JUnit API."""

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from test_public_test_boundary import schema_validator

ROOT = Path(__file__).resolve().parents[1]


class PublicResultSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(
            (ROOT / "schemas/check-result.schema.json").read_text()
        )

    def test_normal_assertion_details_are_accepted(self) -> None:
        case = {
            "id": "case-1",
            "name": "Сумма",
            "status": "failed",
            "expected": "42",
            "actual": "41",
            "message": "Неверная сумма",
            "exceptionType": "org.opentest4j.AssertionFailedError",
            "stackTrace": "AnswerTest.java:12",
            "teacherTrace": "Полный стек",
        }
        validator = schema_validator(
            Draft202012Validator(
                {"$ref": "#/$defs/caseResult", "$defs": self.schema["$defs"]}
            )
        )
        validator.validate(case)

    def test_listener_report_format_is_accepted(self) -> None:
        schema_validator(
            Draft202012Validator(self.schema["properties"]["reportFormat"])
        ).validate("junit-listener")


if __name__ == "__main__":
    unittest.main()
