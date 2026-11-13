"""F0-продолжение настоящих decoder/projection/scorer; production files неизменны."""

from __future__ import annotations

import copy
import importlib.util
import re
import runpy
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    NotRequired,
    Protocol,
    TypedDict,
    TypeGuard,
    runtime_checkable,
)

if TYPE_CHECKING:
    from grading_types import PublicTest, StudentResult


class ExperimentCase(TypedDict):
    id: str
    name: str
    status: str
    checks: NotRequired[list[dict[str, str]]]
    test: NotRequired[str]
    expected: NotRequired[str]
    actual: NotRequired[str]
    message: NotRequired[str]
    exceptionType: NotRequired[str]
    stackTrace: NotRequired[str]
    teacherTrace: NotRequired[str]


class Counts(TypedDict):
    complete: bool
    eventErrors: int
    discovered: int
    executed: int
    passed: int
    failed: int
    skipped: int
    aborted: int
    containerFailures: int
    feedbackProtocolVersion: NotRequired[int]
    registered: list[str]
    started: list[str]
    outcomes: dict[str, str]
    failureKinds: dict[str, str]
    cases: list[ExperimentCase]
    containerDiagnostics: NotRequired[list[dict[str, str]]]


class ObservedCase(TypedDict):
    name: str
    status: str
    expected: NotRequired[str]
    actual: NotRequired[str]
    message: NotRequired[str]
    exceptionType: NotRequired[str]
    stackTrace: NotRequired[str]
    checks: list[dict[str, str]]
    reporter: NotRequired[dict[str, str]]


class Feedback(TypedDict):
    kind: str
    reason: str
    observed: str
    whatCheck: str
    cases: list[ObservedCase]
    feedbackCompleteness: str


class NativeResult(TypedDict):
    gradable: bool
    classification: str
    feedback: Feedback
    message: str
    score: float
    tests: list[PublicTest]


def _untyped_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _mapping(value: object) -> TypeGuard[dict[str, object]]:
    return _untyped_mapping(value) and all(isinstance(key, str) for key in value)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _strings(value: object) -> TypeGuard[list[str]]:
    return _list(value) and all(isinstance(item, str) for item in value)


def _string_map(value: object) -> TypeGuard[dict[str, str]]:
    return _mapping(value) and all(isinstance(item, str) for item in value.values())


def _case(value: object) -> TypeGuard[ExperimentCase]:
    if not _mapping(value) or not all(
        isinstance(value.get(key), str) for key in ("id", "name", "status")
    ):
        return False
    return all(
        (_list(item) and all(_string_map(check) for check in item))
        if key == "checks"
        else isinstance(item, str)
        for key, item in value.items()
    )


def _counts(value: object) -> TypeGuard[Counts]:
    if not _mapping(value) or type(value.get("complete")) is not bool:
        return False
    for key in (
        "eventErrors",
        "discovered",
        "executed",
        "passed",
        "failed",
        "skipped",
        "aborted",
        "containerFailures",
    ):
        if type(value.get(key)) is not int:
            return False
    if (
        "feedbackProtocolVersion" in value
        and type(value["feedbackProtocolVersion"]) is not int
    ):
        return False
    cases = value.get("cases")
    diagnostics = value.get("containerDiagnostics", [])
    return (
        _strings(value.get("registered"))
        and _strings(value.get("started"))
        and _string_map(value.get("outcomes"))
        and _string_map(value.get("failureKinds"))
        and _list(cases)
        and all(_case(case) for case in cases)
        and _list(diagnostics)
        and all(_string_map(item) for item in diagnostics)
    )


def read_counts(value: object) -> Counts:
    """Проверить типы экспериментального JSON, сохранив его поля и значения."""
    if not _counts(value):
        raise ValueError("Invalid experiment counts shape")
    return value


@runtime_checkable
class CountsValidator(Protocol):
    def __call__(self, counts: object, require_cases: bool = True) -> None: ...


@runtime_checkable
class Scorer(Protocol):
    def __call__(
        self, raw: object, counts: object, policy: dict[str, str]
    ) -> float: ...


@runtime_checkable
class Projector(Protocol):
    def __call__(self, result: object, descriptor: object) -> StudentResult: ...


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = {
    "site",
    "property",
    "availability",
    "expected",
    "actual",
    "delta",
    "differenceIndex",
    "differenceExpected",
    "differenceActual",
    "delegated",
}
AUDIT = {"_thread", "_bci", "_snapshotArrayPayloadBytes", "_snapshotArrays"}


def project(counts: object, raw: object) -> NativeResult:
    clean = copy.deepcopy(read_counts(counts))
    observed: dict[str, list[dict[str, str]]] = {}
    for case in clean["cases"]:
        checks = case.pop("checks", [])
        if len(checks) > 64:
            raise ValueError("Invalid checks bound")
        for check in checks:
            if (
                set(check) - PUBLIC - AUDIT
                or not {
                    "site",
                    "property",
                    "availability",
                    "expected",
                    "actual",
                    "delegated",
                }
                <= set(check)
                or any(len(v) > 8192 for v in check.values())
                or not re.fullmatch(r"[\w$.-]+\.java:\d+:\d+", check["site"])
                or check["delegated"] not in ("returned", "threw", "unknown")
            ):
                raise ValueError("Invalid exact check shape")
        observed[case["id"]] = [
            {k: v for k, v in check.items() if k in PUBLIC} for check in checks
        ]
    helpers: dict[str, object] = runpy.run_path(str(ROOT / "runtime/junit_result.py"))
    validate = helpers.get("validate_counts")
    if not isinstance(validate, CountsValidator):
        raise TypeError("Каноническая проверка JUnit недоступна")
    validate(clean)
    spec = importlib.util.spec_from_file_location(
        "f0_grader", ROOT / "images/java25-grader/grade.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Загрузчик локального Python-модуля недоступен")
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    scorer: object = getattr(grader, "_score", None)
    if not isinstance(scorer, Scorer):
        raise TypeError("Канонический scorer недоступен")
    score = scorer(raw, clean, {"mode": "weighted"})
    result = {
        "gradable": True,
        "classification": "behavior-failure" if clean["failed"] else "success",
        "score": score,
        "counts": clean,
    }
    projection_helpers: dict[str, object] = runpy.run_path(
        str(ROOT / "runtime/student_feedback.py")
    )
    projector = projection_helpers.get("student_result")
    if not isinstance(projector, Projector):
        raise TypeError("Каноническая проекция недоступна")
    student = projector(result, {})
    public_cases = student["feedback"].get("cases", [])
    tests = student.get("tests", [])
    cases: list[ObservedCase] = []
    incomplete = False
    for raw_case, case, test in zip(clean["cases"], public_cases, tests, strict=True):
        checks = observed[raw_case["id"]]
        extended: ObservedCase = {**case, "checks": checks}
        cases.append(extended)
        if "expected" in case or "actual" in case:
            extended["reporter"] = {
                "origin": "trusted-TestReporter",
                **({"expected": case["expected"]} if "expected" in case else {}),
                **({"actual": case["actual"]} if "actual" in case else {}),
            }
        lines: list[str] = []
        for check in checks:
            incomplete |= check["availability"] != "complete"
            lines.extend(
                [
                    "Проверка: " + check["property"],
                    "Источник: " + check["site"],
                    "Ожидается: " + check["expected"],
                    "Получено: " + check["actual"],
                ]
            )
            if "differenceIndex" in check:
                lines.append("Первое различие: " + check["differenceIndex"])
        test["description"] += ("\n" if lines else "") + "\n".join(lines)
    if "score" not in student:
        raise AssertionError
    return {
        "gradable": student["gradable"],
        "classification": student["classification"],
        "message": student["message"],
        "score": student["score"],
        "tests": tests,
        "feedback": {
            "kind": student["feedback"]["kind"],
            "reason": student["feedback"]["reason"],
            "observed": student["feedback"]["observed"],
            "whatCheck": student["feedback"]["whatCheck"],
            "cases": cases,
            "feedbackCompleteness": "incomplete" if incomplete else "complete",
        },
    }
