"""Единая проверка событий JUnit на границах исполнителя и квитанции."""


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


CHECK_FIELDS = {
    "site",
    "property",
    "availability",
    "expected",
    "actual",
    "delta",
    "differenceIndex",
    "differenceExpected",
    "differenceActual",
    "differenceLine",
    "differenceColumn",
    "delegated",
}


def validate_checks(checks):
    """Одна точная публичная форма; private authority/audit не принимаются."""
    import re

    if not isinstance(checks, list) or len(checks) > 64:
        raise ValueError("Invalid assertion check bound")
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) - CHECK_FIELDS
            or not {
                "site",
                "property",
                "availability",
                "expected",
                "actual",
                "delegated",
            }
            <= set(check)
            or any(
                not isinstance(v, str) or len(v) > 8192 or len(v.encode("utf-8")) > 8192
                for v in check.values()
            )
            or not re.fullmatch(r"[\w$.-]+\.java:[0-9]+:[0-9]+", check["site"])
            or check["delegated"] not in ("returned", "threw", "unknown")
            or not (
                check["availability"] == "complete"
                or check["availability"].startswith("incomplete: ")
            )
            or any(
                k in check and not re.fullmatch(r"[0-9]+", check[k])
                for k in ("differenceIndex", "differenceLine", "differenceColumn")
            )
        ):
            raise ValueError("Invalid assertion check feedback")


def validate_counts(counts, require_cases=True):
    """Проверить завершённый набор фактических событий до вычисления оценки."""
    if not isinstance(counts, dict):
        raise ValueError("Invalid JUnit event report")
    numeric = (
        "discovered",
        "executed",
        "passed",
        "failed",
        "skipped",
        "aborted",
        "containerFailures",
        "eventErrors",
    )
    if any(type(counts.get(key)) is not int or counts[key] < 0 for key in numeric):
        raise ValueError("Invalid JUnit event counts")
    outcomes = counts.get("outcomes")
    registered, started = counts.get("registered"), counts.get("started")
    if (
        counts.get("complete") is not True
        or counts["eventErrors"]
        or not isinstance(outcomes, dict)
        or any(
            not isinstance(key, str)
            or not key
            or status not in ("successful", "failed", "skipped", "aborted")
            for key, status in outcomes.items()
        )
    ):
        raise ValueError("Incomplete JUnit event report")
    if any(
        not isinstance(ids, list)
        or any(not isinstance(key, str) or not key for key in ids)
        or len(ids) != len(set(ids))
        for ids in (registered, started)
    ):
        raise ValueError("Missing or duplicate JUnit identity")
    if (
        set(registered) != set(outcomes)
        or counts["discovered"] != len(registered)
        or counts["executed"] != len(started)
        or set(started)
        != {key for key, status in outcomes.items() if status != "skipped"}
        or any(
            counts[key] != sum(value == status for value in outcomes.values())
            for key, status in (
                ("passed", "successful"),
                ("failed", "failed"),
                ("skipped", "skipped"),
                ("aborted", "aborted"),
            )
        )
    ):
        raise ValueError("Inconsistent JUnit discovery/execution outcomes")
    failures = counts.get("failureKinds")
    if (
        not isinstance(failures, dict)
        or set(failures)
        != {key for key, status in outcomes.items() if status == "failed"}
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
        raise ValueError("Inconsistent JUnit failure evidence")
    cases = counts.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Missing JUnit case report")
    protocol = counts.get("feedbackProtocolVersion", 1)
    if type(protocol) is not int or protocol not in (1, 2):
        raise ValueError("Invalid assertion feedback protocol")
    ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) - {"id", "name", "status", "expected", "actual", "checks"}
            or not {"id", "name", "status"} <= set(case)
            or any(
                not isinstance(value, str) or len(value) > 8192
                for key, value in case.items()
                if key != "checks"
            )
            or case["id"] not in outcomes
            or case["status"]
            != ("passed" if outcomes[case["id"]] == "successful" else "failed")
        ):
            raise ValueError("Invalid JUnit case feedback")
        if protocol == 2:
            if "checks" not in case:
                raise ValueError("Missing assertion check sequence")
            validate_checks(case["checks"])
        elif "checks" in case:
            raise ValueError("Checks require assertion protocol2")
        ids.append(case["id"])
    if (
        len(ids) != len(set(ids))
        or (require_cases or cases)
        and set(ids) != set(started)
    ):
        raise ValueError("Incomplete JUnit case feedback")


def validate_outcome(value, *, student_tests=False):
    """Принять тот же полный набор и долю после файловой/процессной границы."""
    if "counts" in value:
        counts = value["counts"]
        validate_counts(counts, require_cases=not student_tests)
        if value.get("classification") != "student-test-quality-failure":
            if not counts["executed"] or any(
                counts[key] for key in ("skipped", "aborted", "containerFailures")
            ):
                raise ValueError("Incomplete scored JUnit outcome")
            if "infrastructure" in counts["failureKinds"].values():
                raise ValueError("Trusted failure cannot be a scored outcome")
            if (
                value.get("scoring", {}).get("mode") == "weighted"
                and value.get("score") != counts["passed"] / counts["executed"]
            ):
                raise ValueError(
                    "Weighted score differs from equal completed case fraction"
                )
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
        raise ValueError("Missing complete JUnit outcome")
    if "publicResult" in value:
        validate_outcome(value["publicResult"], student_tests=student_tests)
    for variant in value.get("variants", {}).values():
        validate_outcome(variant, student_tests=True)
