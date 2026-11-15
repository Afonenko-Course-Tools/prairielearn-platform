"""Конечные C3 F0: штатный adapter, изолированные candidate classes, без integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 # trusted experiment runner intentionally starts argv processes
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NotRequired, TypedDict, Unpack

from consumer import Counts, ExperimentCase, read_counts


class Process(TypedDict):
    argv: list[str]
    terminal: str
    seconds: float
    exit_code: NotRequired[int]
    env: NotRequired[dict[str, str | None]]
    stdout: NotRequired[str]
    stderr: NotRequired[str]


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
PROCESSES: list[Process] = []
EXECUTIONS: list[dict[str, object]] = []


def sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command: Sequence[str | Path], cwd: Path, timeout: float = 40) -> str:
    start = time.monotonic()
    try:
        result = subprocess.run(  # nosec B603 # trusted experiment runner uses explicit argv without shell
            list(map(str, command)),
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        PROCESSES.append(
            Process(
                argv=list(map(str, command)),
                terminal="TIMEOUT_KILLED",
                seconds=time.monotonic() - start,
            )
        )
        raise AssertionError("Ограниченный процесс превысил timeout") from error
    PROCESSES.append(
        Process(
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


def java(*args: str | Path) -> list[str | Path]:
    return [JDK / "bin/java", *args]


def javac(*args: str | Path) -> list[str | Path]:
    return [JDK / "bin/javac", "--release", "25", "-g", "-proc:none", *args]


def execute(
    work: Path,
    fixture: Path,
    transformed: bool,
    *,
    student_source: Path | None = None,
    helpers: Sequence[Path] = (),
    quota: int = 32768,
    properties: Sequence[str] = (),
    stale: bool = False,
    student_extra: Sequence[Path] = (),
) -> tuple[Counts, object] | tuple[None, None]:
    work.mkdir()
    observation: dict[str, object] = {
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
            {
                "results_file": str(work / "raw.json"),
                "counts_file": str(work / "counts.json"),
                "signature": "f0-private-signature",
                "test_classes": [fixture.stem],
                "student_classes": [
                    str(p.relative_to(student))[:-6].replace("/", ".")
                    for p in sorted(student.rglob("*.class"))
                ],
                "student_classes_root": str(student),
                "submission_mode": "implementation",
                "public_cases": [],
            }
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
        if not (
            PROCESSES[-1].get("exit_code", None) != 0
            and "Stale trusted class" in PROCESSES[-1].get("stderr", "")
        ):
            raise AssertionError(PROCESSES[-1]) from None
        observation["expected_rejection"] = "stale manifest, before Jupiter"
        if not (not (work / "counts.json").exists()):
            raise AssertionError from None
        return None, None
    if not (len(PROCESSES) == before + 1):
        raise AssertionError
    counts = read_counts(json.loads((work / "counts.json").read_text()))
    raw: object = json.loads((work / "raw.json").read_text())
    observation["counts"] = counts
    observation["raw"] = raw
    return counts, raw


def case(counts: Counts, method: str) -> ExperimentCase:
    return next(c for c in counts["cases"] if ("[method:" + method + "(") in c["id"])


class ExecuteOptions(TypedDict, total=False):
    student_source: Path | None
    helpers: Sequence[Path]
    quota: int
    properties: Sequence[str]
    student_extra: Sequence[Path]


capture_disabled: bool = False


def pair(
    work: Path, name: str, **kwargs: Unpack[ExecuteOptions]
) -> tuple[Counts, Counts, object]:
    fixture = HERE / "fixtures" / name
    left, _raw = execute(work / (name + "-baseline"), fixture, False, **kwargs)
    if not (left is not None):
        raise AssertionError
    right, craw = execute(
        work / (name + "-candidate"), fixture, not capture_disabled, **kwargs
    )
    if not (right is not None):
        raise AssertionError
    if not (left["outcomes"] == right["outcomes"]):
        raise AssertionError((name, left, right))
    if not (left["eventErrors"] == right["eventErrors"] == 0):
        raise AssertionError
    return left, right, craw


def group1(work: Path) -> dict[str, object]:
    _left, right, _raw = pair(work, "TypedTest.java")
    if not ((right["executed"], right["passed"], right["failed"]) == (2, 1, 1)):
        raise AssertionError
    checks = case(right, "typed").get("checks", [])
    if not (len(checks) >= 8):
        raise AssertionError("ordinary assertions have no checks")
    if not (
        [(c["expected"], c["actual"]) for c in checks[:6]]
        == [
            ("42", "42"),
            ("9000000000", "9000000000"),
            ("1.0", "1.01"),
            ("NaN", "NaN"),
            ("-0.0", "0.0"),
            ("null", "null"),
        ]
    ):
        raise AssertionError
    if not (checks[2]["delta"] == ".1" or checks[2]["delta"] == "0.1"):
        raise AssertionError
    if not (not any("differenceIndex" in checks[n] for n in (2, 4))):
        raise AssertionError
    if not (require_checks(case(right, "failed"))[0]["delegated"] == "threw"):
        raise AssertionError
    if not (len({c["site"] for c in checks[:8]}) == 8):
        raise AssertionError
    if not (all(c["_bci"].isdigit() for c in checks)):
        raise AssertionError
    return {
        "status": "PASS",
        "controls": "typed descriptors/category2/boxed null/delta/NaN/zero/lazy supplier/single evaluation/live BCI; same outcomes, tier1 flags only",
    }


def group2(work: Path) -> dict[str, object]:
    _left, right, _raw = pair(
        work,
        "ControlTest.java",
        student_source=HERE / "fixtures/ControlStudent.java",
        helpers=[HERE / "fixtures/TrustedHelper.java"],
    )
    if not (
        (right["executed"], right["passed"], right["containerFailures"]) == (1, 1, 0)
    ):
        raise AssertionError
    if not (
        len(require_checks(right["cases"][0])) == 2
        and all(c["actual"] == "73" for c in require_checks(right["cases"][0]))
    ):
        raise AssertionError
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


def group3(work: Path) -> dict[str, object]:
    props = [
        "-Djunit.jupiter.execution.parallel.enabled=true",
        "-Djunit.jupiter.execution.parallel.config.strategy=fixed",
        "-Djunit.jupiter.execution.parallel.config.fixed.parallelism=4",
    ]
    _left, right, _raw = pair(work, "LeafTest.java", properties=props)
    if not ((right["executed"], right["passed"], right["failed"]) == (6, 6, 0)):
        raise AssertionError
    if not (len({c["id"] for c in right["cases"]}) == 6):
        raise AssertionError
    if not (all(len(require_checks(c)) == 1 for c in right["cases"])):
        raise AssertionError
    if not (
        sorted(require_checks(c)[0]["actual"] for c in right["cases"])
        == [
            "101",
            "11",
            "202",
            "22",
            "31",
            "32",
        ]
    ):
        raise AssertionError
    if not (
        len({require_checks(case(right, m))[0]["_thread"] for m in ["first", "second"]})
        == 2
    ):
        raise AssertionError
    return {
        "status": "PASS",
        "controls": "two same-name parameter rows, two dynamic lambdas, two simultaneous barrier leaves; unique real UIDs, values and worker threads",
    }


def group4(work: Path) -> dict[str, object]:
    _left, right, _raw = pair(work, "TimeoutTest.java")
    if not ((right["executed"], right["passed"], right["failed"]) == (4, 3, 1)):
        raise AssertionError
    if not (
        [
            require_checks(case(right, m))[0]["actual"]
            for m in ["same", "separate", "expires"]
        ]
        == ["12", "34", "56"]
    ):
        raise AssertionError
    if not (
        require_checks(case(right, "same"))[0]["_thread"]
        != require_checks(case(right, "separate"))[0]["_thread"]
    ):
        raise AssertionError
    pre = require_checks(case(right, "preemptive"))
    if not (len(pre) == 1 and "78" not in [c["actual"] for c in pre]):
        raise AssertionError
    if not (pre[0]["availability"].startswith("incomplete")):
        raise AssertionError
    return {
        "status": "UNKNOWN",
        "confirmed": "@Timeout SAME_THREAD, SEPARATE_THREAD, real expired leaf, correct threads/outcomes; finally scope revoked",
        "unsupported": "assertTimeoutPreemptively inner callback has no authenticated scope; inner78 missing, outer observation explicitly incomplete; no inheritance/propagation added",
        "census": "full accepted-surface compiled thread census NOT_RUN",
    }


def group5(work: Path) -> dict[str, object]:
    import copy

    from consumer import project as projection

    _left, right, _raw = pair(work, "ValueTest.java")
    if not (right["passed"] == 4):
        raise AssertionError
    diff = require_checks(case(right, "bytes"))[0]
    if not (
        (
            diff["differenceIndex"],
            diff["differenceExpected"],
            diff["differenceActual"],
            diff["_snapshotArrayPayloadBytes"],
        )
        == ("11017", "01", "02", "24000")
    ):
        raise AssertionError
    if not ("length=12000" in diff["expected"] and "length=12000" in diff["actual"]):
        raise AssertionError
    if not (require_checks(case(right, "actualFixture"))[0]["actual"] == "10003"):
        raise AssertionError
    quota = require_checks(case(right, "quota"))[0]
    if not (
        quota["_snapshotArrayPayloadBytes"] == "0"
        and quota["availability"].startswith("incomplete")
    ):
        raise AssertionError
    seq = require_checks(case(right, "sequences"))
    if not (seq[0]["availability"] == "complete" and "Анна" in seq[0]["actual"]):
        raise AssertionError
    if not ("differenceIndex" not in seq[-1] and seq[-1]["delta"] == "0.1"):
        raise AssertionError
    _a, bounds, _bounds_raw = pair(work, "BoundTest.java")
    if not (bounds["passed"] == 3):
        raise AssertionError
    if not (
        all(
            require_checks(c)[0]["availability"].startswith("incomplete")
            for c in bounds["cases"]
        )
    ):
        raise AssertionError
    if not (all(len(require_checks(c)[0]["actual"]) <= 2048 for c in bounds["cases"])):
        raise AssertionError
    _a, b, quota_raw = pair(work, "QuotaTest.java", quota=256)
    q = require_checks(b["cases"][0])[0]
    if not (q["_snapshotArrays"] == "0"):
        raise AssertionError
    if not (
        q["_snapshotArrayPayloadBytes"] == "0"
        and q["availability"].startswith("incomplete")
    ):
        raise AssertionError
    if not (projection(b, quota_raw)["score"] == 1):
        raise AssertionError
    _a, b, score_raw = pair(work, "ScoreTest.java")
    native = projection(b, score_raw)
    if not (
        (b["executed"], b["passed"], native["score"], len(native["tests"]))
        == (
            10,
            9,
            0.9,
            10,
        )
    ):
        raise AssertionError
    observed = next(
        c
        for c in native["feedback"]["cases"]
        if c["name"] == "Несколько проверок и reporter"
    )
    if not (
        len(observed["checks"]) == 4 and observed["checks"][-1]["delegated"] == "threw"
    ):
        raise AssertionError
    if "reporter" not in observed:
        raise AssertionError
    if not (
        observed["reporter"]["actual"] == "Предметный результат"
        and observed["reporter"]["origin"] == "trusted-TestReporter"
    ):
        raise AssertionError
    if not ("_bci" not in json.dumps(native) and "_thread" not in json.dumps(native)):
        raise AssertionError
    for change in ["unknown-field", "absolute-location", "duplicate-counts"]:
        malformed = copy.deepcopy(b)
        if change == "unknown-field":
            require_checks(malformed["cases"][0])[0]["foreign"] = "x"
        elif change == "absolute-location":
            require_checks(malformed["cases"][0])[0]["site"] = "/private/File.java:1:1"
        else:
            malformed["executed"] += 1
        try:
            projection(malformed, score_raw)
            raise AssertionError("Malformed checks/counts admitted")
        except ValueError:
            pass
    D1 = X / "repos/java-early-projects"
    if not (
        run(["git", "rev-parse", "HEAD"], D1).strip()
        == "8ba3d43d993362f947af0b0889b5717ad3d369c2"
    ):
        raise AssertionError
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
    if not (c is not None):
        raise AssertionError
    if not ((c["executed"], c["passed"]) == (4, 4)):
        raise AssertionError
    if not (
        all(
            any(
                check["property"] == "равенство массивов"
                for check in require_checks(value)
            )
            for value in c["cases"]
        )
    ):
        raise AssertionError
    if not (len(projection(c, reverse_raw)["tests"]) == 4):
        raise AssertionError
    # Original three selected immutable sequence bindings, not a replacement for D1 State.
    archive = X / "private-author-inputs/projects/objects/book-selection"
    forms: dict[str, dict[str, object]] = {}
    for binding, book in [
        ("reference", "course-cases288/reference/Book.java"),
        ("valid-named", "valid-named/Book.java"),
        ("valid-flexible", "valid-flexible/flexible/Book.java"),
    ]:
        c, _rr = execute(
            work / ("book-" + binding),
            archive / "tests/junit/private/ContractTest.java",
            True,
            student_extra=[archive / "tests/fixtures" / book],
            helpers=[archive / "tests/bindings" / binding / "TaskBinding.java"],
        )
        if not (c is not None):
            raise AssertionError
        if not ((c["executed"], c["passed"]) == (2, 2)):
            raise AssertionError
        values = [
            check
            for row in c["cases"]
            for check in require_checks(row)
            if check["actual"].startswith("[[")
        ]
        if not (
            values and all(check["availability"] == "complete" for check in values)
        ):
            raise AssertionError
        forms[binding] = {
            "leaves": 2,
            "value_checks": len(values),
            "availability": "complete",
        }
    book = D1 / "projects/objects/book-selection"
    d1, _rr = execute(
        work / "d1-book",
        book / "checks/src/test/java/BookSelectionTest.java",
        True,
        student_extra=[book / "reference/src/main/java/Book.java"],
    )
    if not (d1 is not None):
        raise AssertionError
    if not ((d1["executed"], d1["passed"]) == (23, 23)):
        raise AssertionError
    first = require_checks(case(d1, "fullConstructor"))[0]
    if not (
        first["availability"].startswith("incomplete")
        and "<opaque:BookSelectionTest$State>" in first["actual"]
    ):
        raise AssertionError
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


def group6(work: Path) -> dict[str, object]:
    _left, right, _raw = pair(
        work, "CallbackTest.java", student_source=HERE / "fixtures/CallbackStudent.java"
    )
    checks = require_checks(case(right, "callbacks"))
    if not (len(checks) == 9):
        raise AssertionError
    if not (
        [c["actual"] for c in checks[:4]]
        == [
            "java.lang.IllegalStateException",
            "java.lang.IllegalStateException",
            "не бросил",
            "Возврат",
        ]
    ):
        raise AssertionError
    if not (
        [c["actual"] for c in checks[-3:]]
        == [
            "true",
            "false",
            "java.lang.IllegalStateException",
        ]
    ):
        raise AssertionError
    if not (
        require_checks(case(right, "before")) == []
        and case(right, "before")["status"] == "failed"
    ):
        raise AssertionError
    if not (not any("differenceIndex" in c for c in checks)):
        raise AssertionError
    return {
        "status": "PASS",
        "controls": "throws correct/wrong/no-throw, doesNotThrow return/failure, BooleanSupplier true/false/throw; nine single callback calls, one lazy message, identical return/Throwable and leaf outcomes; thrown-before-call has no values",
    }


def main() -> None:
    global capture_disabled
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=int, choices=range(1, 7))
    parser.add_argument("--capture-disabled", action="store_true")
    args = parser.parse_args()
    capture_disabled = args.capture_disabled
    if not (os.environ.get("XDG_CACHE_HOME") == "/home/tolya/Java/.cache/codex-tools"):
        raise AssertionError
    groups: dict[str, dict[str, object]] = {
        f"F0-{n}": {"status": "UNKNOWN", "reason": "NOT_RUN"} for n in range(1, 7)
    }
    jdk: dict[str, str] = {}
    receipt: dict[str, object] = {
        "groups": groups,
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
        "jdk": (
            jdk := {
                "release": sha(JDK / "release"),
                "java": sha(JDK / "bin/java"),
                "javac": sha(JDK / "bin/javac"),
            }
        ),
        "jar": {"path": str(JUNIT), "sha256": sha(JUNIT)},
        "integration": "HOLD",
    }
    run(java("-version"), ROOT)
    jdk["version"] = PROCESSES[-1].get("stderr", "")
    work = Path(tempfile.mkdtemp(prefix="c3-f0-v2-final-"))
    evidence = X / ("c3-f0-v2-final-evidence-" + str(time.time_ns()))
    active = None
    try:
        for n in [args.group] if args.group else range(1, 7):
            active = n
            group_work = work / str(n)
            group_work.mkdir()
            before = len(PROCESSES)
            start = time.monotonic()
            groups[f"F0-{n}"] = (group1, group2, group3, group4, group5, group6)[n - 1](
                group_work
            )
            groups[f"F0-{n}"].update(
                seconds=time.monotonic() - start, process_range=[before, len(PROCESSES)]
            )
            print("F0-" + str(n), groups[f"F0-{n}"]["status"], flush=True)
            (X / "c3-f0-v2-checkpoint.json").write_text(
                json.dumps(receipt, indent=2, ensure_ascii=False)
            )
    except Exception as error:
        groups[f"F0-{active}"] = {"status": "FAIL", "reason": str(error)}
        receipt["failure"] = str(error)
        raise
    finally:
        receipt["result"] = (
            "FAIL"
            if any(v["status"] == "FAIL" for v in groups.values())
            else (
                "UNKNOWN"
                if any(v["status"] == "UNKNOWN" for v in groups.values())
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


def require_checks(case: ExperimentCase) -> list[dict[str, str]]:
    """Сохранить обязательное наличие checks в проверках candidate-наблюдений."""
    if "checks" not in case:
        raise KeyError("checks")
    return case["checks"]


if __name__ == "__main__":
    main()
