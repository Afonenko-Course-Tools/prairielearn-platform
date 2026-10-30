"""Конечные C3 F0: штатный adapter, изолированные candidate classes, без integration."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JDK = Path("/usr/lib/jvm/java-25-openjdk")
X = Path("/home/tolya/Java/.cache/codex-tools/refactoring-execution")
BUNDLE = ROOT / "runtime/java25-junit-v1"
JUNIT = BUNDLE / "junit-platform-console-standalone-1.14.1.jar"
LIBS = os.pathsep.join(map(str, (JUNIT, BUNDLE / "json-simple-1.1.1.jar")))
FLAGS = [
    "-Xmx128m",
    "-XX:TieredStopAtLevel=1",
    "-XX:ActiveProcessorCount=2",
    "-XX:-UsePerfData",
    "-XX:+DisableAttachMechanism",
    "--illegal-native-access=deny",
]
PROCESSES = []
EXECUTIONS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, cwd, timeout=40):
    start = time.monotonic()
    try:
        result = subprocess.run(
            list(map(str, command)),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        PROCESSES.append(
            dict(
                argv=list(map(str, command)),
                terminal="TIMEOUT_KILLED",
                seconds=time.monotonic() - start,
            )
        )
        raise AssertionError("Ограниченный процесс превысил timeout") from error
    PROCESSES.append(
        dict(
            argv=list(map(str, command)),
            terminal="EXIT",
            exit_code=result.returncode,
            seconds=time.monotonic() - start,
            env={
                k: os.environ.get(k)
                for k in ("XDG_CACHE_HOME", "JAVA_HOME", "GRADLE_USER_HOME")
            },
            stdout=result.stdout,
            stderr=result.stderr,
        )
    )
    if result.returncode:
        raise AssertionError(
            f"Процесс exit {result.returncode}: {result.stderr[-5000:]} {result.stdout[-1000:]}"
        )
    return result.stdout


def java(*args):
    return [JDK / "bin/java", *args]


def javac(*args):
    return [JDK / "bin/javac", "--release", "25", "-g", "-proc:none", *args]


def execute(
    work,
    fixture,
    transformed,
    *,
    student_source=None,
    helpers=(),
    quota=32768,
    properties=(),
    stale=False,
    student_extra=(),
):
    work.mkdir()
    observation = {
        "mode": "implementation",
        "candidate": transformed,
        "fixture": str(fixture),
        "fixture_sha256": sha(fixture),
        "work": str(work),
        "snapshot_quota": quota,
        "properties": properties,
        "stale_negative": stale,
    }
    observation["additional_source_hashes"] = {
        str(p): sha(p)
        for p in [
            *helpers,
            *student_extra,
            *([student_source] if student_source else []),
        ]
    }
    EXECUTIONS.append(observation)
    adapter = work / "adapter"
    trusted = work / "trusted"
    student = work / "student"
    module = work / "module"
    transform = work / "transform"
    for path in (adapter, trusted, student, module, transform):
        path.mkdir()
    # Both modes use exactly one pinned named JUnit; baseline observer SPI is disabled.
    run(
        javac(
            "--module-path",
            JUNIT,
            "-d",
            module,
            *sorted((HERE / "module").rglob("*.java")),
        ),
        work,
    )
    source = work / "Student.java"
    source.write_text(
        student_source.read_text()
        if student_source
        else "public class Student {public static int answer(){return 42;}}"
    )
    compile_cp = LIBS + os.pathsep + str(module) + os.pathsep + str(student)
    run(javac("-cp", compile_cp, "-d", student, source, *student_extra), work)
    run(javac("-cp", compile_cp, "-d", trusted, fixture, *helpers), work)
    run(javac("-d", transform, HERE / "Transform.java"), work)
    transform_cp = os.pathsep.join(
        map(
            str,
            (
                transform,
                JUNIT,
                BUNDLE / "json-simple-1.1.1.jar",
                trusted,
                student,
                module,
            ),
        )
    )
    if transformed:
        run(
            java(
                "-cp",
                transform_cp,
                "Transform",
                trusted,
                module / "org/prairielearn/feedback/Assertions.class",
                work / "sites.properties",
            ),
            work,
        )
    text = (BUNDLE / "PlatformJUnitAdapter.java").read_text()
    module_flags = [
        "--module-path",
        str(module) + os.pathsep + str(JUNIT),
        "--add-modules",
        "org.prairielearn.feedback",
    ]
    if transformed:
        text = text.replace(
            "    Files.delete(parameterFile);",
            "    Files.delete(parameterFile);\n    org.prairielearn.feedback.Gate.bind();",
        )
        text = text.replace(
            "    discovered = registered.size();",
            "    discovered = registered.size();\n    org.prairielearn.feedback.Gate.register(test.getUniqueId());",
        )
        text = text.replace(
            "      executed++;",
            "      org.prairielearn.feedback.Gate.start(test.getUniqueId());\n      executed++;",
        )
        text = text.replace(
            "    if (result.getStatus() == TestExecutionResult.Status.FAILED) {",
            '    ((Map) report).put("checks", org.prairielearn.feedback.Gate.finish(test.getUniqueId()));\n    if (result.getStatus() == TestExecutionResult.Status.FAILED) {',
        )
    adapter_source = work / "PlatformJUnitAdapter.java"
    adapter_source.write_text(text)
    run(
        javac(
            *module_flags,
            "-cp",
            LIBS,
            "-d",
            adapter,
            adapter_source,
            *sorted((BUNDLE / "upstream").rglob("*.java")),
        ),
        work,
    )
    run(
        java(
            "-cp",
            transform_cp,
            "Transform",
            adapter,
            module / "org/prairielearn/feedback/Assertions.class",
            work / "adapter.properties",
            "adapter",
        ),
        work,
    )
    policy = (work / "adapter.properties").read_text()
    if transformed:
        policy += "\n" + (work / "sites.properties").read_text()
    policy += (
        "\nadapterRoot="
        + str(adapter)
        + "\ntrustedRoot="
        + str(trusted)
        + "\njunitHash="
        + sha(JUNIT)
        + "\nsnapshotBytes="
        + str(quota)
        + "\n"
    )
    if stale:
        policy = policy.replace(
            "class." + fixture.stem + "=", "class." + fixture.stem + "=stale"
        )
    (module / "org/prairielearn/feedback/internal/policy.properties").write_text(policy)
    params = work / "params.json"
    params.write_text(
        json.dumps(
            dict(
                results_file=str(work / "raw.json"),
                counts_file=str(work / "counts.json"),
                signature="f0-private-signature",
                test_classes=[fixture.stem],
                student_classes=[
                    str(p.relative_to(student))[:-6].replace("/", ".")
                    for p in sorted(student.rglob("*.class"))
                ],
                student_classes_root=str(student),
                submission_mode="implementation",
                public_cases=[],
            )
        )
    )
    observation["generated_hashes"] = {
        str(p.relative_to(work)): sha(p) for p in sorted(work.rglob("*")) if p.is_file()
    }
    before = len(PROCESSES)
    try:
        run(
            java(
                *FLAGS,
                *module_flags,
                "-Djunit.jupiter.extensions.autodetection.enabled="
                + str(transformed).lower(),
                *properties,
                "-cp",
                os.pathsep.join(
                    map(
                        str,
                        (adapter, BUNDLE / "json-simple-1.1.1.jar", trusted, student),
                    )
                ),
                "PlatformJUnitAdapter",
                params,
            ),
            work,
        )
    except AssertionError:
        if not stale:
            raise
        assert (
            PROCESSES[-1]["exit_code"] != 0
            and "Stale trusted class" in PROCESSES[-1]["stderr"]
        ), PROCESSES[-1]
        observation["expected_rejection"] = "stale manifest, before Jupiter"
        assert not (work / "counts.json").exists()
        return None, None
    assert len(PROCESSES) == before + 1
    counts = json.loads((work / "counts.json").read_text())
    raw = json.loads((work / "raw.json").read_text())
    observation["counts"] = counts
    observation["raw"] = raw
    return counts, raw


def case(counts, method):
    return next(c for c in counts["cases"] if ("[method:" + method + "(") in c["id"])


def pair(work, name, **kwargs):
    fixture = HERE / "fixtures" / name
    left, raw = execute(work / (name + "-baseline"), fixture, False, **kwargs)
    right, craw = execute(work / (name + "-candidate"), fixture, not DISABLED, **kwargs)
    assert left["outcomes"] == right["outcomes"], (name, left, right)
    assert left["eventErrors"] == right["eventErrors"] == 0
    return left, right, craw


def group1(work):
    left, right, raw = pair(work, "TypedTest.java")
    assert (right["executed"], right["passed"], right["failed"]) == (2, 1, 1)
    checks = case(right, "typed").get("checks", [])
    assert len(checks) >= 8, "ordinary assertions have no checks"
    assert [(c["expected"], c["actual"]) for c in checks[:6]] == [
        ("42", "42"),
        ("9000000000", "9000000000"),
        ("1.0", "1.01"),
        ("NaN", "NaN"),
        ("-0.0", "0.0"),
        ("null", "null"),
    ]
    assert checks[2]["delta"] == ".1" or checks[2]["delta"] == "0.1"
    assert not any("differenceIndex" in checks[n] for n in (2, 4))
    assert case(right, "failed")["checks"][0]["delegated"] == "threw"
    assert len({c["site"] for c in checks[:8]}) == 8
    assert all(c["_bci"].isdigit() for c in checks)
    return {
        "status": "PASS",
        "controls": "typed descriptors/category2/boxed null/delta/NaN/zero/lazy supplier/single evaluation/live BCI; same outcomes, tier1 flags only",
    }


def group2(work):
    left, right, raw = pair(
        work,
        "ControlTest.java",
        student_source=HERE / "fixtures/ControlStudent.java",
        helpers=[HERE / "fixtures/TrustedHelper.java"],
    )
    assert (right["executed"], right["passed"], right["containerFailures"]) == (1, 1, 0)
    assert len(right["cases"][0]["checks"]) == 2 and all(
        c["actual"] == "73" for c in right["cases"][0]["checks"]
    )
    execute(
        work / "stale",
        HERE / "fixtures/ControlTest.java",
        True,
        student_source=HERE / "fixtures/ControlStudent.java",
        helpers=[HERE / "fixtures/TrustedHelper.java"],
        stale=True,
    )
    return {
        "status": "PASS",
        "controls": "four Gate mutators x direct/reflection/MH inside/outside leaf, closed State mutation/lookup/resource, fake SPI, repeat bind, stale hash, wrong site, foreign Class with same CodeSource, helper reentry, child, late; genuine helper remains two checks",
    }


def group3(work):
    props = [
        "-Djunit.jupiter.execution.parallel.enabled=true",
        "-Djunit.jupiter.execution.parallel.config.strategy=fixed",
        "-Djunit.jupiter.execution.parallel.config.fixed.parallelism=4",
    ]
    left, right, raw = pair(work, "LeafTest.java", properties=props)
    assert (right["executed"], right["passed"], right["failed"]) == (6, 6, 0)
    assert len({c["id"] for c in right["cases"]}) == 6
    assert all(len(c["checks"]) == 1 for c in right["cases"])
    assert sorted(c["checks"][0]["actual"] for c in right["cases"]) == [
        "101",
        "11",
        "202",
        "22",
        "31",
        "32",
    ]
    assert (
        len({case(right, m)["checks"][0]["_thread"] for m in ["first", "second"]}) == 2
    )
    return {
        "status": "PASS",
        "controls": "two same-name parameter rows, two dynamic lambdas, two simultaneous barrier leaves; unique real UIDs, values and worker threads",
    }


def group4(work):
    left, right, raw = pair(work, "TimeoutTest.java")
    assert (right["executed"], right["passed"], right["failed"]) == (4, 3, 1)
    assert [
        case(right, m)["checks"][0]["actual"] for m in ["same", "separate", "expires"]
    ] == ["12", "34", "56"]
    assert (
        case(right, "same")["checks"][0]["_thread"]
        != case(right, "separate")["checks"][0]["_thread"]
    )
    pre = case(right, "preemptive")["checks"]
    assert len(pre) == 1 and "78" not in [c["actual"] for c in pre]
    assert pre[0]["availability"].startswith("incomplete")
    return {
        "status": "UNKNOWN",
        "confirmed": "@Timeout SAME_THREAD, SEPARATE_THREAD, real expired leaf, correct threads/outcomes; finally scope revoked",
        "unsupported": "assertTimeoutPreemptively inner callback has no authenticated scope; inner78 missing, outer observation explicitly incomplete; no inheritance/propagation added",
        "census": "full accepted-surface compiled thread census NOT_RUN",
    }


def group5(work):
    import runpy, copy

    projection = runpy.run_path(str(HERE / "consumer.py"))["project"]
    left, right, raw = pair(work, "ValueTest.java")
    assert right["passed"] == 4
    diff = case(right, "bytes")["checks"][0]
    assert (
        diff["differenceIndex"],
        diff["differenceExpected"],
        diff["differenceActual"],
        diff["_snapshotArrayPayloadBytes"],
    ) == ("11017", "01", "02", "24000")
    assert "length=12000" in diff["expected"] and "length=12000" in diff["actual"]
    assert case(right, "actualFixture")["checks"][0]["actual"] == "10003"
    quota = case(right, "quota")["checks"][0]
    assert quota["_snapshotArrayPayloadBytes"] == "0" and quota[
        "availability"
    ].startswith("incomplete")
    seq = case(right, "sequences")["checks"]
    assert seq[0]["availability"] == "complete" and "Анна" in seq[0]["actual"]
    assert "differenceIndex" not in seq[-1] and seq[-1]["delta"] == "0.1"
    a, bounds, bounds_raw = pair(work, "BoundTest.java")
    assert bounds["passed"] == 3
    assert all(
        c["checks"][0]["availability"].startswith("incomplete") for c in bounds["cases"]
    )
    assert all(len(c["checks"][0]["actual"]) <= 2048 for c in bounds["cases"])
    a, b, quota_raw = pair(work, "QuotaTest.java", quota=256)
    q = b["cases"][0]["checks"][0]
    assert q["_snapshotArrays"] == "0"
    assert q["_snapshotArrayPayloadBytes"] == "0" and q["availability"].startswith(
        "incomplete"
    )
    assert projection(b, quota_raw)["score"] == 1
    a, b, score_raw = pair(work, "ScoreTest.java")
    native = projection(b, score_raw)
    assert (b["executed"], b["passed"], native["score"], len(native["tests"])) == (
        10,
        9,
        0.9,
        10,
    )
    observed = next(
        c
        for c in native["feedback"]["cases"]
        if c["name"] == "Несколько проверок и reporter"
    )
    assert (
        len(observed["checks"]) == 4 and observed["checks"][-1]["delegated"] == "threw"
    )
    assert (
        observed["reporter"]["actual"] == "Предметный результат"
        and observed["reporter"]["origin"] == "trusted-TestReporter"
    )
    assert "_bci" not in json.dumps(native) and "_thread" not in json.dumps(native)
    for change in ["unknown-field", "absolute-location", "duplicate-counts"]:
        malformed = copy.deepcopy(b)
        if change == "unknown-field":
            malformed["cases"][0]["checks"][0]["foreign"] = "x"
        elif change == "absolute-location":
            malformed["cases"][0]["checks"][0]["site"] = "/private/File.java:1:1"
        else:
            malformed["executed"] += 1
        try:
            projection(malformed, score_raw)
            raise AssertionError("Malformed checks/counts admitted")
        except ValueError:
            pass
    D1 = X / "repos/java-early-projects"
    assert (
        run(["git", "rev-parse", "HEAD"], D1).strip()
        == "8ba3d43d993362f947af0b0889b5717ad3d369c2"
    )
    reverse = D1 / "projects/arrays/reverse-array"
    c, reverse_raw = execute(
        work / "d1-reverse",
        reverse / "checks/src/test/java/ReverseArrayTest.java",
        True,
        student_extra=[reverse / "reference/src/main/java/Main.java"],
        helpers=[
            D1
            / "projects/common/java/process/src/test/java/coursesupport/JavaProcess.java"
        ],
    )
    assert (c["executed"], c["passed"]) == (4, 4)
    assert all(
        any(check["property"] == "равенство массивов" for check in value["checks"])
        for value in c["cases"]
    )
    assert len(projection(c, reverse_raw)["tests"]) == 4
    # Original three selected immutable sequence bindings, not a replacement for D1 State.
    archive = X / "private-author-inputs/projects/objects/book-selection"
    forms = {}
    for binding, book in [
        ("reference", "course-cases288/reference/Book.java"),
        ("valid-named", "valid-named/Book.java"),
        ("valid-flexible", "valid-flexible/flexible/Book.java"),
    ]:
        c, rr = execute(
            work / ("book-" + binding),
            archive / "tests/junit/private/ContractTest.java",
            True,
            student_extra=[archive / "tests/fixtures" / book],
            helpers=[archive / "tests/bindings" / binding / "TaskBinding.java"],
        )
        assert (c["executed"], c["passed"]) == (2, 2)
        values = [
            check
            for row in c["cases"]
            for check in row["checks"]
            if check["actual"].startswith("[[")
        ]
        assert values and all(check["availability"] == "complete" for check in values)
        forms[binding] = {
            "leaves": 2,
            "value_checks": len(values),
            "availability": "complete",
        }
    book = D1 / "projects/objects/book-selection"
    d1, rr = execute(
        work / "d1-book",
        book / "checks/src/test/java/BookSelectionTest.java",
        True,
        student_extra=[book / "reference/src/main/java/Book.java"],
    )
    assert (d1["executed"], d1["passed"]) == (23, 23)
    first = case(d1, "fullConstructor")["checks"][0]
    assert (
        first["availability"].startswith("incomplete")
        and "<opaque:BookSelectionTest$State>" in first["actual"]
    )
    descriptors = run(
        [
            JDK / "bin/javap",
            "-p",
            "-s",
            work / "d1-book/trusted/BookSelectionTest$State.class",
        ],
        work,
    )
    return {
        "status": "UNKNOWN",
        "M1": "PASS:256byte quota before allocation, allocated0, original failing delegate/message once, unchanged leaf/score1",
        "M2": {
            "status": "PASS",
            "array_bytes": 12000,
            "first_difference": 11017,
            "expected_byte": "01",
            "actual_byte": "02",
            "snapshot_allocated_bytes": 24000,
            "separate_actual_fixture_bytes": 10003,
        },
        "safe_immutable_forms": forms,
        "D1_reverse": "4/4, actual checks helper and integer array values, canonical projection4leaves",
        "consumer_scoring": "canonical decoder/projection/scorer plus candidate checks extension; 10leaf/9pass=.9, reporter separate, caught assertion preserved, unsafe shape rejected",
        "D1_book": {
            "source": str(book / "checks/src/test/java/BookSelectionTest.java"),
            "sha256": sha(book / "checks/src/test/java/BookSelectionTest.java"),
            "leaves": 23,
            "passed": 23,
            "minimal_coverage": first,
            "record_descriptors": descriptors,
            "reason": "required early trusted State record is opaque; safe immutable List form does not cover record fields; no arbitrary reflection/accessor traversal added",
        },
    }


def group6(work):
    left, right, raw = pair(
        work, "CallbackTest.java", student_source=HERE / "fixtures/CallbackStudent.java"
    )
    checks = case(right, "callbacks")["checks"]
    assert len(checks) == 9
    assert [c["actual"] for c in checks[:4]] == [
        "java.lang.IllegalStateException",
        "java.lang.IllegalStateException",
        "не бросил",
        "Возврат",
    ]
    assert [c["actual"] for c in checks[-3:]] == [
        "true",
        "false",
        "java.lang.IllegalStateException",
    ]
    assert (
        case(right, "before")["checks"] == []
        and case(right, "before")["status"] == "failed"
    )
    assert not any("differenceIndex" in c for c in checks)
    return {
        "status": "PASS",
        "controls": "throws correct/wrong/no-throw, doesNotThrow return/failure, BooleanSupplier true/false/throw; nine single callback calls, one lazy message, identical return/Throwable and leaf outcomes; thrown-before-call has no values",
    }


def main():
    global DISABLED
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=int, choices=range(1, 7))
    parser.add_argument("--capture-disabled", action="store_true")
    args = parser.parse_args()
    DISABLED = args.capture_disabled
    assert os.environ.get("XDG_CACHE_HOME") == "/home/tolya/Java/.cache/codex-tools"
    receipt = {
        "groups": {
            f"F0-{n}": {"status": "UNKNOWN", "reason": "NOT_RUN"} for n in range(1, 7)
        },
        "processes": PROCESSES,
        "executions": EXECUTIONS,
        "flags": FLAGS,
        "mode": "implementation",
        "source_head": run(["git", "rev-parse", "HEAD"], ROOT).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT)): sha(p)
            for p in sorted(HERE.rglob("*"))
            if p.suffix in (".java", ".py", ".md")
        },
        "jdk": {
            "release": sha(JDK / "release"),
            "java": sha(JDK / "bin/java"),
            "javac": sha(JDK / "bin/javac"),
        },
        "jar": {"path": str(JUNIT), "sha256": sha(JUNIT)},
        "integration": "HOLD",
    }
    run(java("-version"), ROOT)
    receipt["jdk"]["version"] = PROCESSES[-1]["stderr"]
    work = Path(tempfile.mkdtemp(prefix="c3-f0-v2-final-"))
    evidence = X / ("c3-f0-v2-final-evidence-" + str(time.time_ns()))
    active = None
    try:
        for n in ([args.group] if args.group else range(1, 7)):
            active = n
            group_work = work / str(n)
            group_work.mkdir()
            before = len(PROCESSES)
            start = time.monotonic()
            receipt["groups"][f"F0-{n}"] = globals()["group" + str(n)](group_work)
            receipt["groups"][f"F0-{n}"].update(
                seconds=time.monotonic() - start, process_range=[before, len(PROCESSES)]
            )
            print("F0-" + str(n), receipt["groups"][f"F0-{n}"]["status"], flush=True)
            (X / "c3-f0-v2-checkpoint.json").write_text(
                json.dumps(receipt, indent=2, ensure_ascii=False)
            )
    except Exception as error:
        receipt["groups"][f"F0-{active}"] = {"status": "FAIL", "reason": str(error)}
        receipt["failure"] = str(error)
        raise
    finally:
        receipt["result"] = (
            "FAIL"
            if any(v["status"] == "FAIL" for v in receipt["groups"].values())
            else (
                "UNKNOWN"
                if any(v["status"] == "UNKNOWN" for v in receipt["groups"].values())
                else "PASS"
            )
        )
        shutil.copytree(work, evidence)
        shutil.rmtree(work)
        receipt["evidence_root"] = str(evidence)
        receipt["unfinished_processes"] = []
        (X / "c3-f0-v2-final-receipt.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False)
        )
    raise SystemExit(0 if receipt["result"] == "PASS" else 2)


if __name__ == "__main__":
    main()
