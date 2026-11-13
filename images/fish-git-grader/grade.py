#!/usr/bin/env python3
"""Изолированное выполнение текстового ответа fish и доверенных проверок."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import json
import os
from pathlib import Path
import pwd
import shutil
import tempfile
import time
import types
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    TypeGuard,
    TypedDict,
    runtime_checkable,
)

if TYPE_CHECKING:
    from grading_types import FishGradingDescriptor, Outcome, ResultCounts, Scoring
    from junit_result import RawResult, RawTest


@runtime_checkable
class _Run(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout: float,
        output_limit: int = 65536,
    ) -> tuple[int, str, Literal["timeout", "output_limit"] | None]: ...


@runtime_checkable
class _ProtectInput(Protocol):
    def __call__(self, job: Path) -> None: ...


class _Supervisor(TypedDict):
    run: _Run
    protect_input: _ProtectInput


class _BaseOutcome(TypedDict):
    infrastructure: str
    studentCompilation: str
    trustedCompilation: str
    gradable: bool
    containment: str
    toolchain: str
    scoring: Scoring
    diagnostics: dict[str, str]
    durations: dict[str, float]
    output: str


@runtime_checkable
class _Cases(Protocol):
    def __call__(self, tests: Path) -> object: ...


@runtime_checkable
class _Check(Protocol):
    def __call__(self, root: Path, inputs: dict[str, str]) -> Iterable[object]: ...


@runtime_checkable
class _SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


@runtime_checkable
class _StudentResult(Protocol):
    def __call__(self, result: object, descriptor: object) -> object: ...


def _object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _record(value: object) -> TypeGuard[dict[str, object]]:
    return _object(value) and all(isinstance(key, str) for key in value)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _case(value: object) -> TypeGuard[dict[str, str]]:
    return _record(value) and all(isinstance(text, str) for text in value.values())


def _observation(value: object) -> TypeGuard[list[object] | tuple[object, ...]]:
    return isinstance(value, (list, tuple))


def _validate_schema(validator: object, value: object) -> None:
    if not isinstance(validator, _SchemaValidator):
        raise GraderError("Canonical grading schema validator unavailable")
    validator.validate(value)


def _validated_config(value: object) -> TypeGuard[FishGradingDescriptor]:
    from jsonschema import Draft202012Validator

    schema: object = json.loads(
        (ROOT / "schemas/grading-descriptor.schema.json").read_text()
    )
    if not _record(schema):
        raise GraderError("Canonical grading schema unavailable")
    _validate_schema(Draft202012Validator(schema), value)
    return _record(value) and value.get("runtime") == RUNTIME


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = "fish-git-v1"


class GraderError(Exception):
    pass


def file(root: str | Path, name: object) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or name.startswith("/")
        or any(x in ("", ".", "..") for x in name.split("/"))
    ):
        raise GraderError("Unsafe input path")
    p = Path(root)
    for part in name.split("/"):
        p = p / part
        if p.is_symlink():
            raise GraderError("Symlink input")
    if not p.is_file() or p.stat().st_size > 1048576:
        raise GraderError("Missing or oversized input")
    return p


def preflight() -> _Supervisor:
    registry: object = json.loads((ROOT / "runtime-profiles.json").read_text())
    if (
        not _record(registry)
        or not _record(profiles := registry.get("profiles"))
        or not _record(profile := profiles.get(RUNTIME))
    ):
        raise GraderError("Missing fish runtime profile")
    bundle_name = profile.get("bundle")
    if not isinstance(bundle_name, str):
        raise GraderError("Missing fish runtime profile")
    bundle = ROOT / bundle_name
    supervisor = types.ModuleType("bounded_supervisor")
    exec(
        compile(
            (bundle / "supervisor.py").read_text(),
            str(bundle / "supervisor.py"),
            "exec",
        ),
        supervisor.__dict__,
    )
    if not shutil.which("fish"):
        raise GraderError("fish executable unavailable")
    run: object = supervisor.__dict__.get("_run")
    protect_input: object = supervisor.__dict__.get("_protect_input_identity")
    if not isinstance(run, _Run) or not isinstance(protect_input, _ProtectInput):
        raise GraderError("Fish supervisor unavailable")
    return {"run": run, "protect_input": protect_input}


def grade(job_dir: str | Path) -> Outcome[ResultCounts]:
    entered = time.monotonic()
    job = Path(job_dir).absolute()
    config: object = json.loads(file(job / "tests", "grading-job.json").read_text())
    if (
        not _validated_config(config)
        or config["mode"] != "implementation"
        or len(config["sourceFiles"]) != 1
        or not config["sourceFiles"][0].endswith(".fish")
        or "checks.py" not in config["testFiles"]
    ):
        raise GraderError("Unsupported fish grading contract")
    # Схема уже доказала integer в диапазоне 1..65536, включая integral float.
    # Только byte/slice API получает int; исходный descriptor остаётся прежним.
    output_budget = int(config["limits"]["max-output-bytes"])
    supervisor = preflight()
    official = os.environ.get("PL_CONTAINMENT") == "official"
    prefix: list[str] = []
    if official:
        if os.geteuid() != 0 or not Path("/usr/local/bin/landlock_sandbox").is_file():
            raise GraderError("Official supervisor required")
        supervisor["protect_input"](job)
        job.chmod(0o711)
        for folder in ["student", "tests"]:
            (job / folder).chmod(0o700)
        prefix = ["runuser", "-u", "sbuser", "--", "/usr/local/bin/landlock_sandbox"]
    checker = types.ModuleType("trusted_checks")
    exec(
        compile(
            file(job / "tests", "checks.py").read_text(), "<trusted-checks>", "exec"
        ),
        checker.__dict__,
    )
    make_cases: object = checker.__dict__.get("cases")
    check_case: object = checker.__dict__.get("check")
    if not isinstance(make_cases, _Cases) or not isinstance(check_case, _Check):
        raise GraderError("Trusted checks unavailable")
    base: _BaseOutcome = {
        "infrastructure": "complete",
        "studentCompilation": "success",
        "trustedCompilation": "success",
        "gradable": True,
        "containment": "official-landlock-sbuser" if official else "host-diagnostic",
        "toolchain": "fish",
        "scoring": config["scoring"],
        "diagnostics": {},
        "durations": {},
        "output": "",
    }
    answer_name = config["sourceFiles"][0]
    try:
        source = file(job / "student", answer_name)
        text = source.read_text(encoding="utf-8")
        if "\0" in text:
            raise ValueError("NUL")
    except (GraderError, UnicodeError, ValueError):
        return {
            **base,
            "studentCompilation": "failure",
            "trustedCompilation": "not-run",
            "gradable": False,
            "classification": "unsafe-submission",
            "format_errors": "Передайте объявленный текстовый файл fish в UTF-8",
        }
    cases = make_cases(job / "tests")
    if not _list(cases) or not 1 <= len(cases) <= 16:
        raise GraderError("Trusted checks require 1..16 explicit cases")
    # Syntax parsing executes no answer commands; runtime execution uses sbuser.
    code, output, reason = supervisor["run"](
        ["fish", "--no-config", "--no-execute", str(source)], job, 5
    )
    if reason:
        raise GraderError("fish syntax tool failed")
    if code:
        return {
            **base,
            "studentCompilation": "failure",
            "trustedCompilation": "not-run",
            "gradable": False,
            "classification": "student-compilation-failure",
            "format_errors": "Ошибка синтаксиса fish",
            "output": output,
        }
    observations: list[tuple[str, bool]] = []
    output = ""
    classification: str | None = None
    started = time.monotonic()
    # Leave time for reporting before the container's hard deadline. A student
    # exceeding the shared execution budget must remain a student timeout.
    deadline = entered + max(0, config["limits"]["outer-seconds"] - 0.5)
    for index, case in enumerate(cases):
        with tempfile.TemporaryDirectory(prefix="fish-answer-") as tmp:
            work = Path(tmp)
            answer = work / answer_name
            answer.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, answer)
            if not _object(case):
                raise GraderError("Trusted case must map input paths to UTF-8 text")
            if not _case(case):
                raise GraderError("Unsafe trusted case input")
            for name, text in case.items():
                if (
                    name.startswith("/")
                    or "\\" in name
                    or any(x in ("", ".", "..") for x in name.split("/"))
                    or name == answer_name
                    or len(text.encode("utf-8")) > 65536
                ):
                    raise GraderError("Unsafe trusted case input")
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            if official:
                account = pwd.getpwnam("sbuser")
                os.chown(work, account.pw_uid, account.pw_gid)
                for p in work.rglob("*"):
                    os.chown(p, account.pw_uid, account.pw_gid)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                classification = "student-timeout"
                break
            code, text, reason = supervisor["run"](
                [*prefix, "fish", "--no-config", answer_name],
                work,
                min(config["limits"]["run-seconds"], remaining),
                output_budget,
            )
            output = (output + text)[:output_budget]
            if reason:
                classification = (
                    "student-timeout"
                    if reason == "timeout"
                    else "student-output-overflow"
                )
                break
            if code:
                classification = "student-runtime-failure"
                break
            for observation in check_case(work, case):
                if not _observation(observation) or len(observation) not in (2, 3):
                    raise GraderError(
                        "Trusted check must return name/boolean and optional observed text"
                    )
                name, passed = observation[:2]
                if (
                    not isinstance(name, str)
                    or type(passed) is not bool
                    or len(observation) == 3
                    and not isinstance(observation[2], str)
                ):
                    raise GraderError("Invalid trusted observation")
                binding = str(index) + ": " + name
                observations.append((binding, passed))
    if classification:
        return {
            **base,
            "score": 0,
            "classification": classification,
            "timed_out": classification == "student-timeout",
            "output_limited": classification == "student-output-overflow",
            "message": "Превышен предел выполнения ответа",
            "output": output,
        }
    if len(observations) < config["discovery"]["min-executed"]:
        raise GraderError("No trusted checks executed")
    tests: list[RawTest] = [
        {
            "name": name,
            "description": "",
            "points": int(passed),
            "max_points": 1,
            "output": "",
            "message": "" if passed else "Результат не соответствует условию",
        }
        for name, passed in observations
    ]
    passed = sum(ok for _, ok in observations)
    score = passed / len(observations)
    if config["scoring"]["mode"] == "all-pass":
        score = float(passed == len(observations))
    elif config["scoring"]["mode"] != "weighted":
        raise GraderError("Unsupported fish scoring")
    raw: RawResult = {
        "score": score,
        "points": passed,
        "max_points": len(tests),
        "gradable": True,
        "message": "",
        "output": output,
        "tests": tests,
    }
    counts: ResultCounts = {
        "discovered": len(tests),
        "executed": len(tests),
        "passed": passed,
        "failed": len(tests) - passed,
        "skipped": 0,
        "aborted": 0,
        "containerFailures": 0,
        "outcomes": {
            name: "successful" if ok else "failed" for name, ok in observations
        },
    }
    return {
        **base,
        "score": score,
        "maxPoints": len(tests),
        "classification": "success" if score == 1 else "behavior-failure",
        "rawResult": raw,
        "counts": counts,
        "tests": tests,
        "output": output,
        "durations": {"execution": time.monotonic() - started},
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verification",
        action="store_true",
        help="Private operator verification report",
    )
    args = parser.parse_args()
    job = Path("/grade")
    result: Outcome[ResultCounts]
    try:
        result = grade(job)
        status = 0
    except Exception as error:
        result = {
            "gradable": False,
            "grading_error": True,
            "infrastructure": "failure",
            "classification": "infrastructure-failure",
            "message": str(error),
        }
        status = 2
    output_result: object = result
    if not args.verification:
        import runpy

        boundary: object = runpy.run_path(str(ROOT / "runtime/student_feedback.py"))[
            "student_result"
        ]
        if not isinstance(boundary, _StudentResult):
            raise GraderError("Native feedback boundary unavailable")
        try:
            descriptor: object = json.loads(
                file(job / "tests", "grading-job.json").read_text()
            )
        except (OSError, ValueError):
            descriptor = {}
        output_result = boundary(result, descriptor)
    folder = job / "results"
    folder.mkdir(exist_ok=True)
    folder.chmod(0o700)
    temporary = folder / "results.json.tmp"
    temporary.write_text(json.dumps(output_result, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(folder / "results.json")
    # Return the report to the mounted job owner; sbuser was isolated from that
    # UID before any student command. Do not make the report world-writable.
    if os.geteuid() == 0:
        owner = job.stat()
        os.chown(folder / "results.json", owner.st_uid, owner.st_gid)
        os.chown(folder, owner.st_uid, owner.st_gid)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
