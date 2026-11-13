"""Чтение обычного отчёта публичного слушателя JUnit."""

from collections.abc import Sequence
import json
import math
from pathlib import Path
from typing import NotRequired, TypeGuard, TypedDict, cast


class JUnitCase(TypedDict):
    id: str
    name: str
    status: str
    test: NotRequired[str]
    expected: NotRequired[str]
    actual: NotRequired[str]
    message: NotRequired[str]
    exceptionType: NotRequired[str]
    stackTrace: NotRequired[str]
    teacherTrace: NotRequired[str]


class JUnitCounts(TypedDict):
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
    cases: list[JUnitCase]
    containerDiagnostics: NotRequired[list[dict[str, str]]]


class RawTest(TypedDict):
    name: str
    description: str
    message: str
    output: str
    points: int | float
    max_points: int | float


class RawResult(TypedDict):
    gradable: bool
    tests: list[RawTest]
    score: int | float
    points: int | float
    max_points: int | float
    message: str
    output: str


def unique_json_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _is_object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _record(value: object) -> dict[str, object]:
    if not _is_object(value) or any(not isinstance(key, str) for key in value):
        raise ValueError("Invalid JUnit object")
    return {str(key): item for key, item in value.items()}


def _identifiers(value: object) -> list[str]:
    if not _is_list(value):
        raise ValueError("Invalid JUnit test identifiers")
    result: list[str] = []
    seen: set[str] = set()
    for uid in value:
        if not isinstance(uid, str) or not uid or uid in seen:
            raise ValueError("Invalid JUnit test identifiers")
        result.append(uid)
        seen.add(uid)
    return result


def _strings(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in _record(value).items():
        if not isinstance(item, str):
            raise ValueError("Invalid JUnit string value")
        result[key] = item
    return result


def _number(value: object, message: str) -> int | float:
    if type(value) not in (int, float) or not isinstance(value, (int, float)):
        raise ValueError(message)
    if not math.isfinite(value) or value < 0:
        raise ValueError(message)
    return value


def validate_counts(counts: object, require_cases: bool = True) -> None:
    """Проверить обычную полноту результата, прежде чем вычислять оценку."""
    values = _record(counts)
    if values.get("complete") is not True:
        raise ValueError("Incomplete JUnit report")
    numbers: dict[str, int] = {}
    for name in (
        "discovered",
        "executed",
        "passed",
        "failed",
        "skipped",
        "aborted",
        "containerFailures",
        "eventErrors",
    ):
        value = values.get(name)
        if type(value) is not int or value < 0:
            raise ValueError("Invalid JUnit count: " + name)
        numbers[name] = value
    if numbers["eventErrors"]:
        raise ValueError("Incomplete JUnit events")
    registered = _identifiers(values.get("registered"))
    started = _identifiers(values.get("started"))
    outcomes = _strings(values.get("outcomes"))
    if any(
        status not in ("successful", "failed", "skipped", "aborted")
        for status in outcomes.values()
    ):
        raise ValueError("Invalid JUnit outcomes")
    if (
        set(registered) != set(outcomes)
        or numbers["discovered"] != len(registered)
        or numbers["executed"] != len(started)
        or set(started)
        != {uid for uid, status in outcomes.items() if status != "skipped"}
    ):
        raise ValueError("Incomplete JUnit execution")
    for name, status in (
        ("passed", "successful"),
        ("failed", "failed"),
        ("skipped", "skipped"),
        ("aborted", "aborted"),
    ):
        if numbers[name] != sum(value == status for value in outcomes.values()):
            raise ValueError("Inconsistent JUnit count: " + name)
    failures = _strings(values.get("failureKinds"))
    if set(failures) != {
        uid for uid, status in outcomes.items() if status == "failed"
    } or any(
        kind
        not in ("wrong-answer", "runtime", "timeout", "output-limit", "infrastructure")
        for kind in failures.values()
    ):
        raise ValueError("Invalid JUnit failure kinds")
    cases = values.get("cases")
    if not _is_list(cases):
        raise ValueError("Invalid JUnit cases")
    ids: list[str] = []
    for item in cases:
        case = _strings(item)
        if (
            not {"id", "name", "status"} <= case.keys()
            or set(case) - set(JUnitCase.__annotations__)
            or any(
                len(value) > (32768 if key == "teacherTrace" else 8192)
                for key, value in case.items()
            )
            or case["id"] not in outcomes
            or case["status"]
            != (
                "passed"
                if outcomes[case["id"]] == "successful"
                else outcomes[case["id"]]
            )
        ):
            raise ValueError("Invalid JUnit case")
        ids.append(case["id"])
    if len(ids) != len(set(ids)) or (require_cases and set(ids) != set(outcomes)):
        raise ValueError("Incomplete JUnit cases")


def _checked_counts(value: object, *, require_cases: bool = True) -> JUnitCounts:
    validate_counts(value, require_cases=require_cases)
    # validate_counts checks every field used by the result/scoring boundary.
    return cast(JUnitCounts, value)


def validate_outcome(value: object, *, student_tests: bool = False) -> None:
    value = _record(value)
    if "counts" in value:
        counts = _checked_counts(value["counts"], require_cases=not student_tests)
        if value.get("classification") != "student-test-quality-failure":
            if not counts["executed"] or any(
                counts[name] for name in ("skipped", "aborted", "containerFailures")
            ):
                raise ValueError("Incomplete scored JUnit outcome")
            if "infrastructure" in counts["failureKinds"].values():
                raise ValueError("Trusted failure cannot be scored")
            if (
                _record(value.get("scoring", {})).get("mode") == "weighted"
                and value.get("score") != counts["passed"] / counts["executed"]
            ):
                raise ValueError("Weighted score differs from completed case fraction")
    elif (
        value.get("infrastructure") == "complete"
        and value.get("classification")
        in (
            "success",
            "behavior-failure",
            "student-runtime-failure",
            "student-timeout",
            "student-output-overflow",
            "student-test-quality-failure",
        )
        and "variants" not in value
    ):
        raise ValueError("Missing JUnit outcome")
    if "publicResult" in value:
        validate_outcome(value["publicResult"], student_tests=student_tests)
    for variant in _record(value.get("variants", {})).values():
        validate_outcome(variant, student_tests=True)


def read_junit_report(feedback_file: str | Path) -> tuple[RawResult, JUnitCounts]:
    path = Path(feedback_file)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Oversized JUnit report")
    report = _record(json.loads(path.read_text(), object_pairs_hook=unique_json_object))
    if report.get("complete") is not True:
        raise ValueError("Incomplete JUnit report")
    try:
        outcomes = _strings(report["outcomes"])
        counts = JUnitCounts(
            complete=True,
            eventErrors=0,
            feedbackProtocolVersion=2,
            registered=_identifiers(report["registered"]),
            started=_identifiers(report["started"]),
            outcomes=outcomes,
            discovered=len(_identifiers(report["registered"])),
            executed=len(_identifiers(report["started"])),
            passed=sum(value == "successful" for value in outcomes.values()),
            failed=sum(value == "failed" for value in outcomes.values()),
            skipped=sum(value == "skipped" for value in outcomes.values()),
            aborted=sum(value == "aborted" for value in outcomes.values()),
            containerFailures=_nonnegative_integer(report["containerFailures"]),
            failureKinds=_strings(report["failureKinds"]),
            cases=_report_cases(report["cases"]),
            containerDiagnostics=_diagnostics(report.get("containerDiagnostics", [])),
        )
        validate_counts(counts)
        grading = _record(report["grading"])
        if set(grading) != set(outcomes):
            raise ValueError("Incomplete JUnit grading metadata")
        totals: dict[str, int | float] = {}
        points: int | float = 0
        tests: list[RawTest] = []
        for uid, status in outcomes.items():
            metadata = _record(grading[uid])
            weight = _number(metadata["weight"], "Invalid JUnit grading weight")
            owner = _text(metadata["owner"])
            totals[owner] = totals.get(owner, 0) + weight
            achieved = weight if status == "successful" else 0
            points += achieved
            tests.append(
                RawTest(
                    name=_text(metadata["name"]),
                    description=_text(metadata["description"]),
                    message="",
                    output="",
                    points=achieved,
                    max_points=weight,
                )
            )
        for owner, maximum in _record(report.get("classMaximums", {})).items():
            totals[owner] = _number(maximum, "Invalid JUnit class maximum")
        total = sum(totals.values())
        if not all(math.isfinite(value) for value in (*totals.values(), points, total)):
            raise ValueError("JUnit grading points overflow")
        raw = RawResult(
            gradable=True,
            tests=tests,
            score=min(points / total, 1) if total else 0,
            points=min(points, total),
            max_points=total,
            message="",
            output="",
        )
        return raw, counts
    except (AttributeError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Invalid JUnit report shape") from error


def _nonnegative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Invalid JUnit container failures")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid JUnit grading text")
    return value


def _diagnostics(value: object) -> list[dict[str, str]]:
    if not _is_list(value):
        raise ValueError("Invalid JUnit container diagnostics")
    return [_strings(item) for item in value]


def _report_cases(value: object) -> list[JUnitCase]:
    if not _is_list(value):
        raise ValueError("Invalid JUnit cases")
    # The complete case schema is checked by validate_counts immediately after construction.
    return [cast(JUnitCase, _strings(item)) for item in value]
