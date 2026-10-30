"""Единая проверка событий JUnit на границах исполнителя и квитанции."""


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


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
    ids = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) - {"id", "name", "status", "expected", "actual"}
            or not {"id", "name", "status"} <= set(case)
            or any(
                not isinstance(value, str) or len(value) > 8192
                for value in case.values()
            )
            or case["id"] not in outcomes
            or case["status"]
            != ("passed" if outcomes[case["id"]] == "successful" else "failed")
        ):
            raise ValueError("Invalid JUnit case feedback")
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
