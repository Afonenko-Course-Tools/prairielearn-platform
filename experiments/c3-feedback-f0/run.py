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
from typing import NotRequired, TypedDict, TypeGuard


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


def execute(work: Path, fixture: Path, transformed: bool) -> tuple[Counts, object]:
    work.mkdir()
    observation: dict[str, object] = {
        "mode": "implementation",
        "candidate": transformed,
        "fixture": str(fixture),
        "fixture_sha256": sha(fixture),
        "work": str(work),
    }
    EXECUTIONS.append(observation)
    adapter = work / "adapter"
    trusted = work / "trusted"
    student = work / "student"
    for p in (adapter, trusted, student):
        p.mkdir()
    source = work / "Student.java"
    source.write_text("public class Student {public static int answer(){return 42;}}")
    run(javac("-d", student, source), work)
    run(javac("-cp", LIBS + os.pathsep + str(student), "-d", trusted, fixture), work)
    adapter_source = work / "PlatformJUnitAdapter.java"
    text = (BUNDLE / "PlatformJUnitAdapter.java").read_text()
    module_flags = []
    if transformed:
        module = work / "module"
        module.mkdir()
        compile_flags = ["--add-reads", "org.prairielearn.feedback=ALL-UNNAMED"]
        run(
            javac(
                *compile_flags,
                "-cp",
                LIBS,
                "-d",
                module,
                *sorted((HERE / "module").rglob("*.java")),
            ),
            work,
        )
        transform = work / "transform"
        transform.mkdir()
        run(javac("-d", transform, HERE / "Transform.java"), work)
        run(
            java(
                "-cp",
                transform,
                "Transform",
                trusted,
                module / "org/prairielearn/feedback/Assertions.class",
                work / "sites.properties",
            ),
            work,
        )
        module_flags = [
            "--module-path",
            str(module),
            "--add-modules",
            "org.prairielearn.feedback",
            "--add-reads",
            "org.prairielearn.feedback=ALL-UNNAMED",
        ]
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
    params = work / "params.json"
    params.write_text(
        json.dumps(
            {
                "results_file": str(work / "raw.json"),
                "counts_file": str(work / "counts.json"),
                "signature": "f0-private-signature",
                "test_classes": [fixture.stem],
                "student_classes": ["Student"],
                "student_classes_root": str(student),
                "submission_mode": "implementation",
                "public_cases": [],
            }
        )
    )
    observation["generated_hashes"] = {
        str(p.relative_to(work)): sha(p) for p in sorted(work.rglob("*")) if p.is_file()
    }
    run(
        java(
            *FLAGS,
            *module_flags,
            "-Djunit.jupiter.extensions.autodetection.enabled=true",
            "-cp",
            os.pathsep.join(
                map(
                    str,
                    (
                        adapter,
                        JUNIT,
                        BUNDLE / "json-simple-1.1.1.jar",
                        trusted,
                        student,
                    ),
                )
            ),
            "PlatformJUnitAdapter",
            params,
        ),
        work,
    )
    counts = read_counts(json.loads((work / "counts.json").read_text()))
    raw: object = json.loads((work / "raw.json").read_text())
    observation["counts"] = counts
    observation["raw"] = raw
    return counts, raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-red", action="store_true")
    args = ap.parse_args()
    groups: dict[str, dict[str, object]] = {
        f"F0-{n}": {"status": "UNKNOWN", "reason": "NOT_RUN"} for n in range(1, 7)
    }
    jdk: dict[str, str] = {}
    receipt: dict[str, object] = {
        "groups": groups,
        "processes": PROCESSES,
        "executions": EXECUTIONS,
        "flags": FLAGS,
        "source_head": run(["git", "rev-parse", "HEAD"], ROOT).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT)): sha(p)
            for p in sorted(HERE.rglob("*"))
            if p.is_file()
        },
        "jdk": (
            jdk := {
                "release": sha(JDK / "release"),
                "java": sha(JDK / "bin/java"),
                "javac": sha(JDK / "bin/javac"),
                "version": run(java("-version"), ROOT),
            }
        ),
        "jar": {"path": str(JUNIT), "sha256": sha(JUNIT)},
        "M1": "UNKNOWN: NOT_RUN",
        "M2": {
            "status": "UNKNOWN: NOT_RUN",
            "actual_fixture_bytes": len(("x " * 5000 + "end").encode()),
            "required_diff_index": ">10240",
        },
    }
    jdk["version"] = PROCESSES[-1].get("stderr", "")
    evidence = X / ("c3-f0-evidence-" + str(time.time_ns()))
    work = Path(tempfile.mkdtemp(prefix="c3-f0-"))
    try:
        baseline, _raw = execute(
            work / "baseline", HERE / "fixtures/TypedTest.java", False
        )
        if not (
            (baseline["executed"], baseline["passed"], baseline["failed"])
            == (
                2,
                1,
                1,
            )
        ):
            raise AssertionError(baseline)
        candidate, _craw = execute(
            work / "candidate", HERE / "fixtures/TypedTest.java", not args.baseline_red
        )
        if not (baseline["outcomes"] == candidate["outcomes"]):
            raise AssertionError
        if not (any(case.get("checks") for case in candidate["cases"])):
            raise AssertionError("F0-1: отсутствуют наблюдения обычных assertions")
        groups["F0-1"] = {"status": "PASS"}
    except AssertionError as error:
        receipt["failure"] = str(error)
        if "ResolutionException" in str(error):
            receipt["boot_stdout"] = PROCESSES[-1].get("stdout", "")
            receipt["boot_stderr"] = PROCESSES[-1].get("stderr", "")
            receipt["expected"] = (
                "Boot layer admits closed named observer provider; actual adapter starts Jupiter"
            )
            receipt["actual"] = (
                "Boot layer exit1 before adapter main/Jupiter; no authority or leaf evidence"
            )
            groups["F0-2"] = {
                "status": "FAIL",
                "reason": "Named provider of classpath Extension rejected by boot-layer service resolution; ALL-UNNAMED read edge insufficient",
            }
            groups["F0-1"] = {
                "status": "UNKNOWN",
                "reason": "Baseline two real leaves 1/2; candidate blocked before Jupiter, descriptor/delegate/BCI observations not runtime-qualified",
            }
            for n in range(3, 7):
                groups[f"F0-{n}"] = {
                    "status": "UNKNOWN",
                    "reason": "NOT_RUN: stopped at concrete F0-2 module admission failure",
                }
            receipt["result"] = "FAIL"
            receipt["integration"] = "HOLD"
        else:
            receipt["result"] = "RED" if args.baseline_red else "FAIL"
            receipt["integration"] = "HOLD"
        raise
    finally:
        receipt["processes_unfinished"] = []
        shutil.copytree(work, evidence)
        receipt["evidence_root"] = str(evidence)
        shutil.rmtree(work)
        (
            X
            / ("c3-f0-red-receipt.json" if args.baseline_red else "c3-feasibility.json")
        ).write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
