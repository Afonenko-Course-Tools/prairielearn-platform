"""Guard no-score и реальные compile/API стадии в root и nested outcomes."""

from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable
from jsonschema.exceptions import ValidationError
from selected_job_fixture import fixture_record
import copy
import json
import os
import unittest
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = fixture_record(
    json.loads(
        Path(
            os.environ.get(
                "RESULT_ADMISSION_SCHEMA", ROOT / "schemas/check-result.schema.json"
            )
        ).read_text()
    )
)


@runtime_checkable
class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[ValidationError]: ...


def _validator(value: object) -> _Validator:
    if not isinstance(value, _Validator):
        raise AssertionError("Schema validator недоступен")
    return value


def outcome(
    student: str = "success",
    trusted: str = "not-run",
    api: str | None = None,
    classification: str = "unsafe-submission",
) -> dict[str, object]:
    value: dict[str, object] = {
        "classification": classification,
        "infrastructure": "complete",
        "gradable": False,
        "studentCompilation": student,
        "trustedCompilation": trusted,
        "format_errors": "guard",
        "output": "",
    }
    if classification == "student-compilation-failure":
        value.update(gradable=True, score=0)
    if student == "success" or trusted == "success":
        value.update(
            durations={"studentCompilation": 0.1},
            diagnostics={},
            toolchain="actual JDK25",
        )
        if trusted == "success":
            fixture_record(value["durations"])["trustedCompilation"] = 0.1
    if student == "success":
        value["dependentExecution"] = "not-run"
    if api is not None:
        value.update(apiPrecheck=api, dependentExecution="not-run")
        if api == "success":
            fixture_record(value["durations"]).update(
                apiCompilation=0.1, apiExecution=0.1
            )
    return value


def envelope(
    value: Mapping[str, object], runtime: str = "java25-junit-v1"
) -> dict[str, object]:
    return dict(
        schemaVersion=1,
        scope="declared",
        backend="host",
        qualifiedId="probe/exr-guard",
        scenario="contract:guard",
        runtime=runtime,
        imageDigest=None,
        **value,
    )


class ResultAdmissionTests(unittest.TestCase):
    def check_both(
        self, value: dict[str, object], valid: bool, runtime: str = "java25-junit-v1"
    ) -> None:
        root = envelope(value, runtime)
        nested = copy.deepcopy(value)
        validators: list[tuple[str, object, dict[str, object]]] = [
            ("root", jsonschema.Draft202012Validator(SCHEMA), root),
            (
                "nested",
                jsonschema.Draft202012Validator(
                    {"$ref": "#/$defs/outcome", "$defs": SCHEMA["$defs"]}
                ),
                nested,
            ),
        ]
        for where, candidate, subject in validators:
            validator = _validator(candidate)
            with self.subTest(where=where, value=value):
                errors = list(validator.iter_errors(subject))
                self.assertEqual(
                    not errors, valid, "\n".join(e.message for e in errors)[:1500]
                )

    def test_actual_early_and_post_compile_guard_phases_are_valid(self) -> None:
        for value in [
            outcome("failure"),
            outcome(),
            outcome(api="not-run"),
            outcome(trusted="success"),
            outcome(trusted="success", api="success"),
        ]:
            self.check_both(value, True)

    def test_student_compile_failures_preserve_trusted_first_mutation_fact(
        self,
    ) -> None:
        self.check_both(
            outcome("failure", classification="student-compilation-failure"), True
        )
        self.check_both(
            outcome(
                "failure", api="not-run", classification="student-compilation-failure"
            ),
            True,
        )
        self.check_both(
            outcome(
                "failure",
                trusted="success",
                classification="student-compilation-failure",
            ),
            True,
            "java25-mutation-v1",
        )

    def test_student_compile_failure_never_claims_dependent_execution(self) -> None:
        # Independent receipt claims: javac failed, so dependent execution cannot have run.
        for trusted, runtime in [
            ("not-run", "java25-junit-v1"),
            ("success", "java25-mutation-v1"),
        ]:
            value = outcome(
                "failure", trusted, classification="student-compilation-failure"
            )
            value["dependentExecution"] = "complete"
            self.check_both(value, False, runtime)

    def test_student_compile_failure_never_has_execution_duration(self) -> None:
        for trusted, runtime in [
            ("not-run", "java25-junit-v1"),
            ("success", "java25-mutation-v1"),
        ]:
            value = outcome(
                "failure", trusted, classification="student-compilation-failure"
            )
            fixture_record(value.setdefault("durations", {}))["execution"] = 0.1
            self.check_both(value, False, runtime)

    def test_student_compile_failure_optional_not_run_is_valid(self) -> None:
        for trusted, runtime in [
            ("not-run", "java25-junit-v1"),
            ("success", "java25-mutation-v1"),
        ]:
            value = outcome(
                "failure", trusted, classification="student-compilation-failure"
            )
            value["dependentExecution"] = "not-run"
            self.check_both(value, True, runtime)

    def test_unsafe_can_never_claim_grade_or_behavior_execution(self) -> None:
        mutations: list[dict[str, object]] = [
            {"score": 0},
            {"score": 1},
            {"maxPoints": 1},
            {"gradable": True},
            {"dependentExecution": "complete"},
            {"grading_error": True},
        ]
        for initial in [outcome("failure"), outcome()]:
            for change in mutations:
                value = copy.deepcopy(initial)
                value.update(change)
                self.check_both(value, False)
            value = copy.deepcopy(initial)
            fixture_record(value.setdefault("durations", {}))["execution"] = 0.1
            self.check_both(value, False)

    def test_impossible_compile_or_api_stage_combinations_fail_closed(self) -> None:
        for value in [
            outcome("not-run"),
            outcome("failure", "success"),
            outcome(trusted="failure"),
            outcome(api="success"),
            outcome(trusted="success", api="not-run"),
            outcome(api="failure"),
        ]:
            self.check_both(value, False)

    def test_post_compile_claims_require_corresponding_actual_phase_evidence(
        self,
    ) -> None:
        for trusted, api, keys in [
            ("not-run", None, ["studentCompilation"]),
            ("success", None, ["studentCompilation", "trustedCompilation"]),
            (
                "success",
                "success",
                [
                    "studentCompilation",
                    "trustedCompilation",
                    "apiCompilation",
                    "apiExecution",
                ],
            ),
        ]:
            for key in keys:
                value = outcome(trusted=trusted, api=api)
                fixture_record(value["durations"]).pop(key)
                self.check_both(value, False)
        for key in ["durations", "diagnostics", "toolchain", "dependentExecution"]:
            value = outcome()
            value.pop(key)
            self.check_both(value, False)

    def test_api_not_run_does_not_allow_hidden_api_execution(self) -> None:
        for student in ["failure", "success"]:
            value = outcome(student, api="not-run")
            fixture_record(value.setdefault("durations", {}))["apiExecution"] = 0.1
            self.check_both(value, False)

    def test_mutation_compile_failure_cannot_claim_api_precheck(self) -> None:
        value = outcome("failure", "success", "not-run", "student-compilation-failure")
        self.check_both(value, False, "java25-mutation-v1")

    def test_trusted_first_student_compile_failure_is_not_an_implementation_stage(
        self,
    ) -> None:
        value = outcome(
            "failure", "success", classification="student-compilation-failure"
        )
        validator = _validator(jsonschema.Draft202012Validator(SCHEMA))
        errors = list(validator.iter_errors(envelope(value)))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
