"""Чтение обычного отчёта публичного слушателя JUnit."""

from collections.abc import Sequence
import json
import math
from pathlib import Path
from typing import NotRequired, TypedDict


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


def validate_counts(counts: object, require_cases: bool = True) -> None:
    """Проверить обычную полноту результата, прежде чем вычислять оценку."""
    if not isinstance(counts, dict) or counts.get("complete") is not True:
        raise ValueError("Incomplete JUnit report")
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
        if type(counts.get(name)) is not int or counts[name] < 0:
            raise ValueError("Invalid JUnit count: " + name)
    if counts["eventErrors"]:
        raise ValueError("Incomplete JUnit events")
    registered, started = counts.get("registered"), counts.get("started")
    outcomes, failures, cases = (
        counts.get("outcomes"),
        counts.get("failureKinds"),
        counts.get("cases"),
    )
    for ids in (registered, started):
        if (
            not isinstance(ids, list)
            or any(not isinstance(uid, str) or not uid for uid in ids)
            or len(ids) != len(set(ids))
        ):
            raise ValueError("Invalid JUnit test identifiers")
    if not isinstance(outcomes, dict) or any(
        not isinstance(uid, str)
        or status not in ("successful", "failed", "skipped", "aborted")
        for uid, status in outcomes.items()
    ):
        raise ValueError("Invalid JUnit outcomes")
    if (
        set(registered) != set(outcomes)
        or counts["discovered"] != len(registered)
        or counts["executed"] != len(started)
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
        if counts[name] != sum(value == status for value in outcomes.values()):
            raise ValueError("Inconsistent JUnit count: " + name)
    if (
        not isinstance(failures, dict)
        or set(failures)
        != {uid for uid, status in outcomes.items() if status == "failed"}
        or any(
            kind
            not in (
                "wrong-answer",
                "runtime",
                "timeout",
                "output-limit",
                "infrastructure",
            )
            for kind in failures.values()
        )
    ):
        raise ValueError("Invalid JUnit failure kinds")
    if not isinstance(cases, list):
        raise ValueError("Invalid JUnit cases")
    ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not {"id", "name", "status"} <= case.keys()
            or set(case) - set(JUnitCase.__annotations__)
            or any(
                not isinstance(value, str)
                or len(value) > (32768 if key == "teacherTrace" else 8192)
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


def validate_outcome(value: object, *, student_tests: bool = False) -> None:
    if not isinstance(value, dict):
        raise ValueError("Invalid JUnit outcome")
    if "counts" in value:
        validate_counts(value["counts"], require_cases=not student_tests)
        counts = value["counts"]
        if value.get("classification") != "student-test-quality-failure":
            if not counts["executed"] or any(
                counts[name] for name in ("skipped", "aborted", "containerFailures")
            ):
                raise ValueError("Incomplete scored JUnit outcome")
            if "infrastructure" in counts["failureKinds"].values():
                raise ValueError("Trusted failure cannot be scored")
            if (
                value.get("scoring", {}).get("mode") == "weighted"
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
    for variant in value.get("variants", {}).values():
        validate_outcome(variant, student_tests=True)


def read_junit_report(feedback_file: str | Path) -> tuple[RawResult, JUnitCounts]:
    path = Path(feedback_file)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Oversized JUnit report")
    report = json.loads(path.read_text(), object_pairs_hook=unique_json_object)
    if not isinstance(report, dict) or report.get("complete") is not True:
        raise ValueError("Incomplete JUnit report")
    try:
        outcomes = report["outcomes"]
        counts = JUnitCounts(
            complete=True,
            eventErrors=0,
            feedbackProtocolVersion=2,
            registered=report["registered"],
            started=report["started"],
            outcomes=outcomes,
            discovered=len(report["registered"]),
            executed=len(report["started"]),
            passed=sum(value == "successful" for value in outcomes.values()),
            failed=sum(value == "failed" for value in outcomes.values()),
            skipped=sum(value == "skipped" for value in outcomes.values()),
            aborted=sum(value == "aborted" for value in outcomes.values()),
            containerFailures=report["containerFailures"],
            failureKinds=report["failureKinds"],
            cases=report["cases"],
            containerDiagnostics=report.get("containerDiagnostics", []),
        )
        validate_counts(counts)
        grading = report["grading"]
        if set(grading) != set(outcomes):
            raise ValueError("Incomplete JUnit grading metadata")
        totals: dict[str, int | float] = {}
        points: int | float = 0
        tests: list[RawTest] = []
        for uid, status in outcomes.items():
            metadata = grading[uid]
            weight = metadata["weight"]
            if (
                type(weight) not in (int, float)
                or not math.isfinite(weight)
                or weight < 0
            ):
                raise ValueError("Invalid JUnit grading weight")
            owner = metadata["owner"]
            totals[owner] = totals.get(owner, 0) + weight
            achieved = weight if status == "successful" else 0
            points += achieved
            tests.append(
                RawTest(
                    name=metadata["name"],
                    description=metadata["description"],
                    message="",
                    output="",
                    points=achieved,
                    max_points=weight,
                )
            )
        for owner, maximum in report.get("classMaximums", {}).items():
            if (
                type(maximum) not in (int, float)
                or not math.isfinite(maximum)
                or maximum < 0
            ):
                raise ValueError("Invalid JUnit class maximum")
            totals[owner] = maximum
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
