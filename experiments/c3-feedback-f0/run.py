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


def execute(work, fixture, transformed):
    work.mkdir()
    observation = {
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
            dict(
                results_file=str(work / "raw.json"),
                counts_file=str(work / "counts.json"),
                signature="f0-private-signature",
                test_classes=[fixture.stem],
                student_classes=["Student"],
                student_classes_root=str(student),
                submission_mode="implementation",
                public_cases=[],
            )
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
    counts = json.loads((work / "counts.json").read_text())
    raw = json.loads((work / "raw.json").read_text())
    observation["counts"] = counts
    observation["raw"] = raw
    return counts, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-red", action="store_true")
    args = ap.parse_args()
    receipt = {
        "groups": {
            f"F0-{n}": {"status": "UNKNOWN", "reason": "NOT_RUN"} for n in range(1, 7)
        },
        "processes": PROCESSES,
        "executions": EXECUTIONS,
        "flags": FLAGS,
        "source_head": run(["git", "rev-parse", "HEAD"], ROOT).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT)): sha(p)
            for p in sorted(HERE.rglob("*"))
            if p.is_file()
        },
        "jdk": {
            "release": sha(JDK / "release"),
            "java": sha(JDK / "bin/java"),
            "javac": sha(JDK / "bin/javac"),
            "version": run(java("-version"), ROOT),
        },
        "jar": {"path": str(JUNIT), "sha256": sha(JUNIT)},
        "M1": "UNKNOWN: NOT_RUN",
        "M2": {
            "status": "UNKNOWN: NOT_RUN",
            "actual_fixture_bytes": len(("x " * 5000 + "end").encode()),
            "required_diff_index": ">10240",
        },
    }
    receipt["jdk"]["version"] = PROCESSES[-1]["stderr"]
    evidence = X / ("c3-f0-evidence-" + str(time.time_ns()))
    work = Path(tempfile.mkdtemp(prefix="c3-f0-"))
    try:
        baseline, raw = execute(
            work / "baseline", HERE / "fixtures/TypedTest.java", False
        )
        assert (baseline["executed"], baseline["passed"], baseline["failed"]) == (
            2,
            1,
            1,
        ), baseline
        candidate, craw = execute(
            work / "candidate", HERE / "fixtures/TypedTest.java", not args.baseline_red
        )
        assert baseline["outcomes"] == candidate["outcomes"]
        assert any(
            case.get("checks") for case in candidate["cases"]
        ), "F0-1: отсутствуют наблюдения обычных assertions"
        receipt["groups"]["F0-1"] = {"status": "PASS"}
    except AssertionError as error:
        receipt["failure"] = str(error)
        if "ResolutionException" in str(error):
            receipt["boot_stdout"] = PROCESSES[-1]["stdout"]
            receipt["boot_stderr"] = PROCESSES[-1]["stderr"]
            receipt["expected"] = (
                "Boot layer admits closed named observer provider; actual adapter starts Jupiter"
            )
            receipt["actual"] = (
                "Boot layer exit1 before adapter main/Jupiter; no authority or leaf evidence"
            )
            receipt["groups"]["F0-2"] = {
                "status": "FAIL",
                "reason": "Named provider of classpath Extension rejected by boot-layer service resolution; ALL-UNNAMED read edge insufficient",
            }
            receipt["groups"]["F0-1"] = {
                "status": "UNKNOWN",
                "reason": "Baseline two real leaves 1/2; candidate blocked before Jupiter, descriptor/delegate/BCI observations not runtime-qualified",
            }
            for n in range(3, 7):
                receipt["groups"][f"F0-{n}"] = {
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
