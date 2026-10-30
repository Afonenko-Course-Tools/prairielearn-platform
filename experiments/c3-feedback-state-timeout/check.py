"""Адресная проверка State/preemptive; конечные children, без product integration."""

import json, shutil, tempfile, time, traceback
from pathlib import Path
import run as base


def state(work):
    book = base.X / "repos/java-early-projects/projects/objects/book-selection"
    source = book / "checks/src/test/java/BookSelectionTest.java"
    assert (
        base.sha(source)
        == "8e5bf83de1ee7332d0fdb03474407949677be51bc6ee4035fc0b866c210ae719"
    )
    baseline, _ = base.execute(
        work / "book-baseline",
        source,
        False,
        student_extra=[book / "reference/src/main/java/Book.java"],
    )
    counts, raw = base.execute(
        work / "book",
        source,
        True,
        student_extra=[book / "reference/src/main/java/Book.java"],
        projection_types=["BookSelectionTest$State"],
    )
    assert (counts["executed"], counts["passed"]) == (23, 23)
    c = base.case(counts, "fullConstructor")["checks"][0]
    assert c["availability"] == "complete", c
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
        assert literal in c["actual"], (literal, c)
    assert baseline["outcomes"] == counts["outcomes"]
    assert all(
        x["availability"] == "complete"
        for leaf in counts["cases"]
        for x in leaf["checks"]
    )
    arrays = [
        x
        for leaf in counts["cases"]
        for x in leaf["checks"]
        if x["property"] == "равенство массивов" and "id=" in x["actual"]
    ]
    assert arrays and all(
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
    mutant = work / "faulty-input"
    mutant.mkdir()
    file = mutant / "Book.java"
    reference = (book / "reference/src/main/java/Book.java").read_text()
    assert reference.count("publisher = value;") == 1
    file.write_text(reference.replace("publisher = value;", 'publisher = value + "!";'))
    badbase, _ = base.execute(
        work / "book-faulty-baseline", source, False, student_extra=[file]
    )
    bad, badraw = base.execute(
        work / "book-faulty",
        source,
        True,
        student_extra=[file],
        projection_types=["BookSelectionTest$State"],
    )
    assert bad["outcomes"] == badbase["outcomes"] and (
        bad["executed"],
        bad["passed"],
        bad["failed"],
    ) == (23, 22, 1), bad
    differing = base.case(bad, "changePublisher")["checks"][0]
    assert (
        'publisher="Мир"' in differing["expected"]
        and 'publisher="Мир!"' in differing["actual"]
        and differing["delegated"] == "threw"
    ), differing
    from consumer import project

    assert (
        project(counts, raw)["score"] == 1
        and abs(project(bad, badraw)["score"] - 22 / 23) < 1e-12
    )
    return {
        "status": "PASS",
        "counts": [23, 23],
        "first": c,
        "array_checks": len(arrays),
        "faulty": differing,
    }


def records(work):
    counts, raw = base.execute(
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
    assert (counts["executed"], counts["passed"]) == (7, 7), counts
    assert not base.case(counts, "earlyThrow")["checks"]
    first = base.case(counts, "singleEvaluation")["checks"][0]
    assert (
        first["availability"] == "complete"
        and "\n" not in first["actual"]
        and r"null\n\"заголовок" in first["actual"]
    ), first
    nulls = base.case(counts, "unsupported")["checks"][1]
    assert (
        "title=null" in nulls["actual"]
        and 'authors=["null"]' in nulls["actual"]
        and nulls["availability"] == "complete"
    ), nulls
    assert base.case(counts, "nestedSafe")["checks"][0]["availability"] == "complete"
    difference = base.case(counts, "nestedSafe")["checks"][1]
    assert (
        difference["differenceIndex"],
        difference["differenceExpected"],
        difference["differenceActual"],
    ) == ("11017", "01", "02"), difference
    for name in ("customListNeverRead", "cycle", "unsupported"):
        assert any(
            c["availability"].startswith("incomplete")
            for c in base.case(counts, name)["checks"]
        ), name
    authority = base.case(counts, "authority")["checks"]
    assert len(authority) == 5, authority
    assert authority[0]["availability"].startswith("incomplete") and authority[1][
        "availability"
    ].startswith("incomplete")
    assert (
        "id=13" in authority[2]["actual"] and authority[2]["availability"] == "complete"
    )
    return {"status": "PASS", "cases": counts["cases"]}


def provenance_bounds(work):
    fixture = base.HERE / "fixtures/RecordTest.java"
    options = dict(
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
    low, raw = base.execute(work / "record-quota16", fixture, True, quota=16, **options)
    assert baseline["outcomes"] == low["outcomes"] and low["passed"] == 7, (
        baseline,
        low,
    )
    first = base.case(low, "singleEvaluation")["checks"][0]
    assert (
        first["availability"].startswith("incomplete")
        and first["_snapshotRecordNodes"]
        == first["_snapshotRecordComponents"]
        == first["_snapshotArrays"]
        == "0"
    ), first
    base.execute(work / "record-stale", fixture, True, stale=True, **options)
    base.execute(
        work / "record-schema",
        fixture,
        True,
        policy_edit=lambda p: p.replace("id\\:I", "other\\:I"),
        expected_rejection="Stale projection schema",
        **options
    )

    def mutate(trusted):
        path = trusted / "RecordTest$Value.class"
        data = path.read_bytes()
        assert data.count(b"$pl$c3$component") == 1
        path.write_bytes(data.replace(b"$pl$c3$component", b"$pl$c3$componenx"))

    base.execute(
        work / "record-bridge-stale",
        fixture,
        True,
        trusted_edit=mutate,
        expected_rejection="Stale trusted class",
        **options
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
        assert (
            "Reserved projection collision" in base.PROCESSES[-1]["stderr"]
        ), base.PROCESSES[-1]
        assert not (work / "collision/counts.json").exists()
    else:
        raise AssertionError("collision admitted")
    controls, _ = base.execute(
        work / "entry-controls",
        base.HERE / "fixtures/ControlTest.java",
        True,
        student_source=base.HERE / "fixtures/ControlStudent.java",
        helpers=[base.HERE / "fixtures/TrustedHelper.java"],
    )
    assert (
        controls["passed"] == 1 and len(controls["cases"][0]["checks"]) == 2
    ), controls
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


def integration(work):
    from consumer import project
    import copy

    counts, raw = base.execute(
        work / "score", base.HERE / "fixtures/ScoreTest.java", True
    )
    native = project(counts, raw)
    assert (counts["executed"], counts["passed"], counts["failed"]) == (10, 9, 1)
    assert native["score"] == 0.9 and len(native["tests"]) == 10, native
    ordinary = next(c for c in native["feedback"]["cases"] if "reporter" in c)
    assert ordinary["reporter"] == {
        "origin": "trusted-TestReporter",
        "expected": "Предметное ожидание",
        "actual": "Предметный результат",
    }, ordinary
    public = json.dumps(native, ensure_ascii=False)
    assert not any(
        name in public
        for name in ("_snapshot", "_bci", "_thread", "Grant", "java.lang.Class")
    ), public
    for corruption in ("grant", "path", "counts"):
        bad = copy.deepcopy(counts)
        if corruption == "grant":
            bad["cases"][0]["checks"][0]["grant"] = {"raw": "object"}
        elif corruption == "path":
            bad["cases"][0]["checks"][0]["site"] = "/host/internal.java:1:1"
        else:
            bad["passed"] += 1
        try:
            project(bad, raw)
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


def preemptive(work):
    options = dict(
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
        **options
    )
    right, raw = base.execute(
        work / "preemptive-candidate",
        base.HERE / "fixtures/PreemptiveTest.java",
        True,
        **options
    )
    assert left["outcomes"] == right["outcomes"] and right["failed"] == 0, (left, right)
    restore = base.case(right, "parentRestore")["checks"]
    assert [c["actual"] for c in restore] == ["77", "не бросил", "78", "79"], restore
    assert restore[0]["_thread"] == restore[-1]["_thread"] != restore[2]["_thread"]
    late = base.case(right, "lateRevoke")["checks"]
    assert {"701", "703", "704"} <= {c["actual"] for c in late} and not any(
        c["actual"] == "702" for c in late
    ), late
    denied = base.case(right, "workerDenied")["checks"]
    assert [c["actual"] for c in denied] == ["не бросил", "801", "802"], denied
    ancestor = base.case(right, "ancestorRevoke")["checks"]
    assert {"811", "814"} <= {c["actual"] for c in ancestor}, ancestor
    assert not any(c["actual"] == "812" for c in ancestor), ancestor
    nested = base.case(right, "nested")["checks"]
    assert {"501", "502", "503"} <= {c["actual"] for c in nested}, nested
    deep = base.case(right, "depthLimit")["checks"]
    assert any(
        c["availability"].startswith("incomplete: timeout depth") for c in deep
    ), deep
    assert not any(c["actual"] == "600" for c in deep)
    parameters = [
        c for c in right["cases"] if "[test-template:parameter(int)]" in c["id"]
    ]
    assert len(parameters) == 2 and len({c["id"] for c in parameters}) == 2
    for c in parameters:
        values = [x["actual"] for x in c["checks"]]
        assert ("101" in values) != ("202" in values), c
    dynamic = [c for c in right["cases"] if "[dynamic-test:" in c["id"]]
    assert len(dynamic) == 2 and len({c["id"] for c in dynamic}) == 2
    return {"status": "PASS", "cases": right["cases"], "outcomes": right["outcomes"]}


def publication(work):
    result = {}
    for stage in ("commit", "end"):
        counts, raw = base.execute(
            work / ("publication-" + stage),
            base.HERE / "fixtures/PublicationTest.java",
            True,
            diagnostic_pause=stage,
        )
        assert (counts["executed"], counts["passed"]) == (2, 2), counts
        pending = base.case(counts, "freezePending")["checks"][1]
        assert pending["delegated"] == "unknown" and pending["availability"].startswith(
            "incomplete: pending"
        ), pending
        if stage == "commit":
            assert pending["actual"] == pending["expected"] == "<unavailable>", pending
        else:
            assert pending["actual"] == pending["expected"] == "901", pending
        after = base.case(counts, "releaseAfterFinish")["checks"]
        assert [c["actual"] for c in after] == ["902"], after
        from consumer import project

        native = project(counts, raw)
        assert (
            native["score"] == 1
            and native["feedback"]["feedbackCompleteness"] == "incomplete"
            and len(native["tests"]) == 2
        )
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


def grants(work):
    counts, raw = base.execute(
        work / "grant-controls",
        base.HERE / "fixtures/GrantTest.java",
        True,
        diagnostic_pause="grant",
    )
    assert (counts["executed"], counts["passed"]) == (1, 1), counts
    checks = counts["cases"][0]["checks"]
    actual = [c["actual"] for c in checks]
    assert {"989", "993", "995", "4"} <= set(actual) and not {
        "990",
        "991",
        "992",
    } & set(actual), checks
    return {
        "status": "PASS",
        "mode": "diagnostic closed-module controls, actual pinned JUnit workers",
        "checks": checks,
    }


def timeout(work):
    counts, raw = base.execute(
        work / "timeout", base.HERE / "fixtures/TimeoutTest.java", True
    )
    c = base.case(counts, "preemptive")
    assert any(x["actual"] == "78" and x["expected"] == "78" for x in c["checks"]), c
    return {"status": "PASS", "case": c}


def main():
    stamp = str(time.time_ns())
    work = Path(tempfile.mkdtemp(prefix="c3-state-timeout-"))
    receipt = {
        "groups": {},
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
                receipt["groups"][name] = fn(work)
            except Exception as e:
                receipt["groups"][name] = {
                    "status": "FAIL",
                    "reason": str(e),
                    "trace": traceback.format_exc(),
                }
            receipt["groups"][name]["seconds"] = time.monotonic() - begin
            print(name, receipt["groups"][name]["status"], flush=True)
    finally:
        evidence = base.X / ("c3-state-timeout-evidence-" + stamp)
        shutil.copytree(work, evidence)
        shutil.rmtree(work)
        receipt["evidence_root"] = str(evidence)
        receipt["unfinished_processes"] = []
        target = base.X / ("c3-state-timeout-run-" + stamp + ".json")
        target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
        print(target)
    raise SystemExit(
        1 if any(v["status"] != "PASS" for v in receipt["groups"].values()) else 0
    )


if __name__ == "__main__":
    main()
