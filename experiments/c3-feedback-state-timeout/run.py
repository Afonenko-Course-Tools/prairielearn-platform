"""Конечные C3 F0: штатный adapter, изолированные candidate classes, без integration."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 # trusted experiment runner intentionally starts argv processes
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NotRequired, TypedDict

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
                for k in ("XDG_CACHE_HOME", "JAVA_HOME", "GRADLE_USER_HOME", "PATH")
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
    projection_types: Sequence[str] = (),
    diagnostic_pause: str | None = None,
    policy_edit: Callable[[str], str] | None = None,
    expected_rejection: str | None = None,
    trusted_edit: Callable[[Path], None] | None = None,
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
        "diagnostic_pause": diagnostic_pause,
        "projection_types": projection_types,
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
    module_source = HERE / "module"
    if diagnostic_pause:
        module_source = work / "diagnostic-module-source"
        shutil.copytree(HERE / "module", module_source)
        for source in (HERE / "diagnostics").rglob("*.java"):
            target = module_source / source.relative_to(HERE / "diagnostics")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        state_source = module_source / "org/prairielearn/feedback/internal/State.java"
        state_text = state_source.read_text()
        commit_anchor = "      synchronized (LOCK) {\n        if (live(context)) {\n          handle.values = check;"
        if not (state_text.count(commit_anchor) == 1):
            raise AssertionError
        state_text = state_text.replace(
            commit_anchor,
            '      if (context.grant != null) PublicationProbe.pause("commit");\n'
            + commit_anchor,
        )
        end_anchor = "    if (check == null)\n      return;\n    synchronized (LOCK) {\n      if (check.ready && live(check.context))"
        if not (state_text.count(end_anchor) == 1):
            raise AssertionError
        state_text = state_text.replace(
            end_anchor,
            '    if (check == null)\n      return;\n    if (check.context.grant != null) PublicationProbe.pause("end");\n    synchronized (LOCK) {\n      if (check.ready && live(check.context))',
        )
        finish_anchor = "      return List.copyOf(result);"
        if not (state_text.count(finish_anchor) == 1):
            raise AssertionError
        state_text = state_text.replace(
            finish_anchor,
            "      var frozen=List.copyOf(result); PublicationProbe.capture(frozen); return frozen;",
        )
        state_source.write_text(state_text)
        properties = (*properties, "-Dc3.pause=" + diagnostic_pause)
    run(
        javac(
            "--module-path",
            JUNIT,
            "-d",
            module,
            *sorted(module_source.rglob("*.java")),
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
                *([",".join(projection_types)] if projection_types else []),
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
    run(
        java(
            "-cp",
            transform_cp,
            "Transform",
            "reader",
            module / "org/prairielearn/feedback/internal/State.class",
            work / "reader.properties",
        ),
        work,
    )
    policy = (
        (work / "adapter.properties").read_text()
        + "\n"
        + (work / "reader.properties").read_text()
    )
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
    if policy_edit:
        policy = policy_edit(policy)
    (module / "org/prairielearn/feedback/internal/policy.properties").write_text(policy)
    if trusted_edit:
        trusted_edit(trusted)
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
        if not stale and not expected_rejection:
            raise
        if not (
            PROCESSES[-1].get("exit_code", None) != 0
            and (expected_rejection or "Stale trusted class")
            in PROCESSES[-1].get("stderr", "")
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


def require_checks(case: ExperimentCase) -> list[dict[str, str]]:
    """Сохранить обязательное наличие checks в проверках candidate-наблюдений."""
    if "checks" not in case:
        raise KeyError("checks")
    return case["checks"]
