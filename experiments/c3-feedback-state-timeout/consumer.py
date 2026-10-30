"""F0-продолжение настоящих decoder/projection/scorer; production files неизменны."""

import copy
import importlib.util
import re
import runpy
from pathlib import Path

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
AUDIT = {
    "_thread",
    "_bci",
    "_snapshotArrayPayloadBytes",
    "_snapshotArrays",
    "_snapshotRecordNodes",
    "_snapshotRecordComponents",
}


def project(counts, raw):
    clean = copy.deepcopy(counts)
    observed = {}
    for case in clean["cases"]:
        checks = case.pop("checks", [])
        if not isinstance(checks, list) or len(checks) > 64:
            raise ValueError("Invalid checks bound")
        for check in checks:
            if (
                not isinstance(check, dict)
                or set(check) - PUBLIC - AUDIT
                or not {
                    "site",
                    "property",
                    "availability",
                    "expected",
                    "actual",
                    "delegated",
                }
                <= set(check)
                or any(not isinstance(v, str) or len(v) > 8192 for v in check.values())
                or not re.fullmatch(r"[\w$.-]+\.java:\d+:\d+", check["site"])
                or check["delegated"] not in ("returned", "threw", "unknown")
            ):
                raise ValueError("Invalid exact check shape")
        observed[case["id"]] = [
            {k: v for k, v in check.items() if k in PUBLIC} for check in checks
        ]
    runpy.run_path(str(ROOT / "runtime/junit_result.py"))["validate_counts"](clean)
    spec = importlib.util.spec_from_file_location(
        "f0_grader", ROOT / "images/java25-grader/grade.py"
    )
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    score = grader._score(raw, clean, {"mode": "weighted"})
    result = {
        "gradable": True,
        "classification": "behavior-failure" if clean["failed"] else "success",
        "score": score,
        "counts": clean,
    }
    native = runpy.run_path(str(ROOT / "runtime/student_feedback.py"))[
        "student_result"
    ](result, {})
    incomplete = False
    for raw_case, case, test in zip(
        clean["cases"], native["feedback"]["cases"], native["tests"]
    ):
        checks = observed[raw_case["id"]]
        case["checks"] = checks
        if "expected" in case or "actual" in case:
            case["reporter"] = {
                "origin": "trusted-TestReporter",
                **{k: case[k] for k in ("expected", "actual") if k in case},
            }
        lines = []
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
    native["feedback"]["feedbackCompleteness"] = (
        "incomplete" if incomplete else "complete"
    )
    return native
