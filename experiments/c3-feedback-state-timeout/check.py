"""Адресная проверка State/preemptive; конечные children, без product integration."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

import run as base

LOGGER = logging.getLogger(__name__)


class RecordOptions(TypedDict):
    student_extra: Sequence[Path]
    helpers: Sequence[Path]
    projection_types: Sequence[str]


class PreemptiveOptions(TypedDict):
    student_source: Path
    helpers: Sequence[Path]
    properties: Sequence[str]


def state(work: Path) -> dict[str, object]:
    book = base.X / "repos/java-early-projects/projects/objects/book-selection"
    source = book / "checks/src/test/java/BookSelectionTest.java"
    if not (
        base.sha(source)
        == "8e5bf83de1ee7332d0fdb03474407949677be51bc6ee4035fc0b866c210ae719"
    ):
        raise AssertionError
    baseline, _ = base.execute(
        work / "book-baseline",
        source,
        False,
        student_extra=[book / "reference/src/main/java/Book.java"],
    )
    if not (baseline is not None):
        raise AssertionError
    counts, raw = base.execute(
        work / "book",
        source,
        True,
        student_extra=[book / "reference/src/main/java/Book.java"],
        projection_types=["BookSelectionTest$State"],
    )
    if not (counts is not None):
        raise AssertionError
    if not ((counts["executed"], counts["passed"]) == (23, 23)):
        raise AssertionError
    c = base.require_checks(base.case(counts, "fullConstructor"))[0]
    if not (c["availability"] == "complete"):
        raise AssertionError(c)
    for literal in (
        "id=17",
        "title=",
        "Массивы",
        "authors=",
        "Анна",
        "Борис",
        "publisher=",
        "Свет",
        "year=2024",
        "pages=312",
        "price=19.75",
        "binding=",
        "Твёрдый",
    ):
        if literal not in c["actual"]:
            raise AssertionError((literal, c))
    if not (baseline["outcomes"] == counts["outcomes"]):
        raise AssertionError
    if not (
        all(
            x["availability"] == "complete"
            for leaf in counts["cases"]
            for x in base.require_checks(leaf)
        )
    ):
        raise AssertionError
    arrays = [
        x
        for leaf in counts["cases"]
        for x in base.require_checks(leaf)
        if x["property"] == "равенство массивов" and "id=" in x["actual"]
    ]
    if not (
        arrays
        and all(
            all(
                field in x["actual"]
                for field in (
                    "id=",
                    "title=",
                    "authors=",
                    "publisher=",
                    "year=",
                    "pages=",
                    "price=",
                    "binding=",
                )
            )
            for x in arrays
        )
    ):
        raise AssertionError
    mutant = work / "faulty-input"
    mutant.mkdir()
    file = mutant / "Book.java"
    reference = (book / "reference/src/main/java/Book.java").read_text()
    if not (reference.count("publisher = value;") == 1):
        raise AssertionError
    file.write_text(reference.replace("publisher = value;", 'publisher = value + "!";'))
    badbase, _ = base.execute(
        work / "book-faulty-baseline", source, False, student_extra=[file]
    )
    if not (badbase is not None):
        raise AssertionError
    bad, badraw = base.execute(
        work / "book-faulty",
        source,
        True,
        student_extra=[file],
        projection_types=["BookSelectionTest$State"],
    )
    if not (bad is not None):
        raise AssertionError
    if not (
        bad["outcomes"] == badbase["outcomes"]
        and (
            bad["executed"],
            bad["passed"],
            bad["failed"],
        )
        == (23, 22, 1)
    ):
        raise AssertionError(bad)
    differing = base.require_checks(base.case(bad, "changePublisher"))[0]
    if not (
        'publisher="Мир"' in differing["expected"]
        and 'publisher="Мир!"' in differing["actual"]
        and differing["delegated"] == "threw"
    ):
        raise AssertionError(differing)
    from consumer import project

    if not (
        project(counts, raw)["score"] == 1
        and abs(project(bad, badraw)["score"] - 22 / 23) < 1e-12
    ):
        raise AssertionError
    return {
        "status": "PASS",
        "counts": [23, 23],
        "first": c,
        "array_checks": len(arrays),
        "faulty": differing,
    }


def records(work: Path) -> dict[str, object]:
    counts, _raw = base.execute(
        work / "records",
        base.HERE / "fixtures/RecordTest.java",
        True,
        student_extra=[base.HERE / "fixtures/RecordStudent.java"],
        projection_types=[
            "RecordTest$Value",
            "RecordTest$Envelope",
            "RecordTest$Unsupported",
            "ProjectionTwin",
        ],
        helpers=[base.HERE / "fixtures/ProjectionTwin.java"],
    )
    if not (counts is not None):
        raise AssertionError
    if not ((counts["executed"], counts["passed"]) == (7, 7)):
        raise AssertionError(counts)
    if not (not base.require_checks(base.case(counts, "earlyThrow"))):
        raise AssertionError
    first = base.require_checks(base.case(counts, "singleEvaluation"))[0]
    if not (
        first["availability"] == "complete"
        and "\n" not in first["actual"]
        and r"null\n\"заголовок" in first["actual"]
    ):
        raise AssertionError(first)
    nulls = base.require_checks(base.case(counts, "unsupported"))[1]
    if not (
        "title=null" in nulls["actual"]
        and 'authors=["null"]' in nulls["actual"]
        and nulls["availability"] == "complete"
    ):
        raise AssertionError(nulls)
    if not (
        base.require_checks(base.case(counts, "nestedSafe"))[0]["availability"]
        == "complete"
    ):
        raise AssertionError
    difference = base.require_checks(base.case(counts, "nestedSafe"))[1]
    if not (
        (
            difference["differenceIndex"],
            difference["differenceExpected"],
            difference["differenceActual"],
        )
        == ("11017", "01", "02")
    ):
        raise AssertionError(difference)
    for name in ("customListNeverRead", "cycle", "unsupported"):
        if not (
            any(
                c["availability"].startswith("incomplete")
                for c in base.require_checks(base.case(counts, name))
            )
        ):
            raise AssertionError(name)
    authority = base.require_checks(base.case(counts, "authority"))
    if not (len(authority) == 5):
        raise AssertionError(authority)
    if not (
        authority[0]["availability"].startswith("incomplete")
        and authority[1]["availability"].startswith("incomplete")
    ):
        raise AssertionError
    if not (
        "id=13" in authority[2]["actual"] and authority[2]["availability"] == "complete"
    ):
        raise AssertionError
    return {"status": "PASS", "cases": counts["cases"]}


def provenance_bounds(work: Path) -> dict[str, object]:
    fixture = base.HERE / "fixtures/RecordTest.java"
    options = RecordOptions(
        student_extra=[base.HERE / "fixtures/RecordStudent.java"],
        helpers=[base.HERE / "fixtures/ProjectionTwin.java"],
        projection_types=[
            "RecordTest$Value",
            "RecordTest$Envelope",
            "RecordTest$Unsupported",
            "ProjectionTwin",
        ],
    )
    baseline, _ = base.execute(
        work / "record-baseline",
        fixture,
        False,
        student_extra=options["student_extra"],
        helpers=options["helpers"],
    )
    if not (baseline is not None):
        raise AssertionError
    low, _raw = base.execute(
        work / "record-quota16", fixture, True, quota=16, **options
    )
    if not (low is not None):
        raise AssertionError
    if not (baseline["outcomes"] == low["outcomes"] and low["passed"] == 7):
        raise AssertionError(
            (
                baseline,
                low,
            )
        )
    first = base.require_checks(base.case(low, "singleEvaluation"))[0]
    if not (
        first["availability"].startswith("incomplete")
        and first["_snapshotRecordNodes"]
        == first["_snapshotRecordComponents"]
        == first["_snapshotArrays"]
        == "0"
    ):
        raise AssertionError(first)
    base.execute(work / "record-stale", fixture, True, stale=True, **options)
    base.execute(
        work / "record-schema",
        fixture,
        True,
        policy_edit=lambda p: p.replace("id\\:I", "other\\:I"),
        expected_rejection="Stale projection schema",
        **options,
    )

    def mutate(trusted: Path) -> None:
        path = trusted / "RecordTest$Value.class"
        data = path.read_bytes()
        if not (data.count(b"$pl$c3$component") == 1):
            raise AssertionError
        path.write_bytes(data.replace(b"$pl$c3$component", b"$pl$c3$componenx"))

    base.execute(
        work / "record-bridge-stale",
        fixture,
        True,
        trusted_edit=mutate,
        expected_rejection="Stale trusted class",
        **options,
    )
    collision = work / "CollisionTest.java"
    collision.write_text(
        "import org.junit.jupiter.api.*; public class CollisionTest { record Value(int id) { public Object $pl$c3$component(int n){return null;} } @Test void ok() {} }"
    )
    try:
        base.execute(
            work / "collision",
            collision,
            True,
            projection_types=["CollisionTest$Value"],
        )
    except AssertionError:
        if "Reserved projection collision" not in base.PROCESSES[-1].get("stderr", ""):
            raise AssertionError(base.PROCESSES[-1]) from None
        if not (not (work / "collision/counts.json").exists()):
            raise AssertionError from None
    else:
        raise AssertionError("collision admitted")
    controls, _ = base.execute(
        work / "entry-controls",
        base.HERE / "fixtures/ControlTest.java",
        True,
        student_source=base.HERE / "fixtures/ControlStudent.java",
        helpers=[base.HERE / "fixtures/TrustedHelper.java"],
    )
    if not (controls is not None):
        raise AssertionError
    if not (
        controls["passed"] == 1 and len(base.require_checks(controls["cases"][0])) == 2
    ):
        raise AssertionError(controls)
    return {
        "status": "PASS",
        "quota16": first,
        "entry_controls": controls["cases"],
        "rejections": [
            "stale class",
            "schema",
            "bridge bytes",
            "reserved method collision",
        ],
    }


def integration(work: Path) -> dict[str, object]:
    import copy

    from consumer import project

    counts, raw = base.execute(
        work / "score", base.HERE / "fixtures/ScoreTest.java", True
    )
    if not (counts is not None):
        raise AssertionError
    native = project(counts, raw)
    if not ((counts["executed"], counts["passed"], counts["failed"]) == (10, 9, 1)):
        raise AssertionError
    if not (native["score"] == 0.9 and len(native["tests"]) == 10):
        raise AssertionError(native)
    ordinary = next(c for c in native["feedback"]["cases"] if "reporter" in c)
    if not (
        ordinary["reporter"]
        == {
            "origin": "trusted-TestReporter",
            "expected": "Предметное ожидание",
            "actual": "Предметный результат",
        }
    ):
        raise AssertionError(ordinary)
    public = json.dumps(native, ensure_ascii=False)
    if not (
        not any(
            name in public
            for name in ("_snapshot", "_bci", "_thread", "Grant", "java.lang.Class")
        )
    ):
        raise AssertionError(public)
    for corruption in ("grant", "path", "counts"):
        bad = copy.deepcopy(counts)
        invalid: object = bad
        if corruption == "grant":
            invalid = {
                **bad,
                "cases": [
                    {
                        **bad["cases"][0],
                        "checks": [
                            {
                                **base.require_checks(bad["cases"][0])[0],
                                "grant": {"raw": "object"},
                            },
                            *base.require_checks(bad["cases"][0])[1:],
                        ],
                    },
                    *bad["cases"][1:],
                ],
            }
        elif corruption == "path":
            base.require_checks(bad["cases"][0])[0]["site"] = "/host/internal.java:1:1"
        else:
            bad["passed"] += 1
        try:
            project(invalid, raw)
        except (ValueError, AssertionError):
            pass
        else:
            raise AssertionError("unsafe consumer input accepted: " + corruption)
    return {
        "status": "PASS",
        "score": native["score"],
        "native_tests": len(native["tests"]),
        "ordinary": ordinary,
    }


def preemptive(work: Path) -> dict[str, object]:
    options = PreemptiveOptions(
        student_source=base.HERE / "fixtures/ControlStudent.java",
        helpers=[base.HERE / "fixtures/TrustedHelper.java"],
        properties=[
            "-Djunit.jupiter.execution.parallel.enabled=true",
            "-Djunit.jupiter.execution.parallel.mode.default=same_thread",
            "-Djunit.jupiter.execution.parallel.config.strategy=fixed",
            "-Djunit.jupiter.execution.parallel.config.fixed.parallelism=4",
        ],
    )
    left, _ = base.execute(
        work / "preemptive-baseline",
        base.HERE / "fixtures/PreemptiveTest.java",
        False,
        **options,
    )
    if not (left is not None):
        raise AssertionError
    right, _raw = base.execute(
        work / "preemptive-candidate",
        base.HERE / "fixtures/PreemptiveTest.java",
        True,
        **options,
    )
    if not (right is not None):
        raise AssertionError
    if not (left["outcomes"] == right["outcomes"] and right["failed"] == 0):
        raise AssertionError((left, right))
    restore = base.require_checks(base.case(right, "parentRestore"))
    if not ([c["actual"] for c in restore] == ["77", "не бросил", "78", "79"]):
        raise AssertionError(restore)
    if not (restore[0]["_thread"] == restore[-1]["_thread"] != restore[2]["_thread"]):
        raise AssertionError
    late = base.require_checks(base.case(right, "lateRevoke"))
    if not (
        {"701", "703", "704"} <= {c["actual"] for c in late}
        and not any(c["actual"] == "702" for c in late)
    ):
        raise AssertionError(late)
    denied = base.require_checks(base.case(right, "workerDenied"))
    if not ([c["actual"] for c in denied] == ["не бросил", "801", "802"]):
        raise AssertionError(denied)
    ancestor = base.require_checks(base.case(right, "ancestorRevoke"))
    if not ({"811", "814"} <= {c["actual"] for c in ancestor}):
        raise AssertionError(ancestor)
    if not (not any(c["actual"] == "812" for c in ancestor)):
        raise AssertionError(ancestor)
    nested = base.require_checks(base.case(right, "nested"))
    if not ({"501", "502", "503"} <= {c["actual"] for c in nested}):
        raise AssertionError(nested)
    deep = base.require_checks(base.case(right, "depthLimit"))
    if not (
        any(c["availability"].startswith("incomplete: timeout depth") for c in deep)
    ):
        raise AssertionError(deep)
    if not (not any(c["actual"] == "600" for c in deep)):
        raise AssertionError
    parameters = [
        c for c in right["cases"] if "[test-template:parameter(int)]" in c["id"]
    ]
    if not (len(parameters) == 2 and len({c["id"] for c in parameters}) == 2):
        raise AssertionError
    for c in parameters:
        values = [x["actual"] for x in base.require_checks(c)]
        if not (("101" in values) != ("202" in values)):
            raise AssertionError(c)
    dynamic = [c for c in right["cases"] if "[dynamic-test:" in c["id"]]
    if not (len(dynamic) == 2 and len({c["id"] for c in dynamic}) == 2):
        raise AssertionError
    return {"status": "PASS", "cases": right["cases"], "outcomes": right["outcomes"]}


def publication(work: Path) -> dict[str, object]:
    result: dict[str, dict[str, object]] = {}
    for stage in ("commit", "end"):
        counts, raw = base.execute(
            work / ("publication-" + stage),
            base.HERE / "fixtures/PublicationTest.java",
            True,
            diagnostic_pause=stage,
        )
        if not (counts is not None):
            raise AssertionError
        if not ((counts["executed"], counts["passed"]) == (2, 2)):
            raise AssertionError(counts)
        pending = base.require_checks(base.case(counts, "freezePending"))[1]
        if not (
            pending["delegated"] == "unknown"
            and pending["availability"].startswith("incomplete: pending")
        ):
            raise AssertionError(pending)
        if stage == "commit":
            if not (pending["actual"] == pending["expected"] == "<unavailable>"):
                raise AssertionError(pending)
        else:
            if not (pending["actual"] == pending["expected"] == "901"):
                raise AssertionError(pending)
        after = base.require_checks(base.case(counts, "releaseAfterFinish"))
        if not ([c["actual"] for c in after] == ["902"]):
            raise AssertionError(after)
        from consumer import project

        native = project(counts, raw)
        if not (
            native["score"] == 1
            and native["feedback"]["feedbackCompleteness"] == "incomplete"
            and len(native["tests"]) == 2
        ):
            raise AssertionError
        result[stage] = {
            "pending": pending,
            "outcomes": counts["outcomes"],
            "consumer_score": native["score"],
        }
    return {
        "status": "PASS",
        "mode": "diagnostic-pause-only, same lifecycle implementation",
        "controls": result,
    }


def grants(work: Path) -> dict[str, object]:
    counts, _raw = base.execute(
        work / "grant-controls",
        base.HERE / "fixtures/GrantTest.java",
        True,
        diagnostic_pause="grant",
    )
    if not (counts is not None):
        raise AssertionError
    if not ((counts["executed"], counts["passed"]) == (1, 1)):
        raise AssertionError(counts)
    checks = base.require_checks(counts["cases"][0])
    actual = [c["actual"] for c in checks]
    if not (
        {"989", "993", "995", "4"} <= set(actual)
        and not {
            "990",
            "991",
            "992",
        }
        & set(actual)
    ):
        raise AssertionError(checks)
    return {
        "status": "PASS",
        "mode": "diagnostic closed-module controls, actual pinned JUnit workers",
        "checks": checks,
    }


def timeout(work: Path) -> dict[str, object]:
    counts, _raw = base.execute(
        work / "timeout", base.HERE / "fixtures/TimeoutTest.java", True
    )
    if not (counts is not None):
        raise AssertionError
    c = base.case(counts, "preemptive")
    if not (
        any(
            x["actual"] == "78" and x["expected"] == "78"
            for x in base.require_checks(c)
        )
    ):
        raise AssertionError(c)
    return {"status": "PASS", "case": c}


def main() -> None:
    stamp = str(time.time_ns())
    work = Path(tempfile.mkdtemp(prefix="c3-state-timeout-"))
    groups: dict[str, dict[str, object]] = {}
    receipt: dict[str, object] = {
        "groups": groups,
        "processes": base.PROCESSES,
        "executions": base.EXECUTIONS,
        "source_hashes": {
            str(p.relative_to(base.ROOT)): base.sha(p)
            for p in base.HERE.rglob("*")
            if p.is_file() and p.suffix in (".java", ".py")
        },
        "jar": {"path": str(base.JUNIT), "sha256": base.sha(base.JUNIT)},
        "jdk": {
            name: base.sha(base.JDK / name)
            for name in ("release", "bin/java", "bin/javac")
        },
        "flags": base.FLAGS,
        "mode": "implementation + explicitly marked diagnostic pause/closed-module controls",
        "source_head": base.run(["git", "rev-parse", "HEAD"], base.ROOT).strip(),
        "integration": "HOLD",
    }
    try:
        for name, fn in [
            ("S1", state),
            ("S2-S4", records),
            ("S3-S4", provenance_bounds),
            ("T2", timeout),
            ("T1-T4", preemptive),
            ("T3-publication", publication),
            ("T4-grants", grants),
            ("I1", integration),
        ]:
            begin = time.monotonic()
            try:
                groups[name] = fn(work)
            except Exception as e:
                LOGGER.exception("Не пройдена группа %s", name)
                groups[name] = {
                    "status": "FAIL",
                    "reason": str(e),
                    "trace": traceback.format_exc(),
                }
            groups[name]["seconds"] = time.monotonic() - begin
            print(name, groups[name]["status"], flush=True)
    finally:
        evidence = base.X / ("c3-state-timeout-evidence-" + stamp)
        shutil.copytree(work, evidence)
        shutil.rmtree(work)
        receipt["evidence_root"] = str(evidence)
        receipt["unfinished_processes"] = []
        target = base.X / ("c3-state-timeout-run-" + stamp + ".json")
        target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
        print(target)
    raise SystemExit(1 if any(v["status"] != "PASS" for v in groups.values()) else 0)


if __name__ == "__main__":
    main()
