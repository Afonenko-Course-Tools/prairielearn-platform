#!/usr/bin/env python3
"""Compile allowlisted Java sources and run course-owned checks on JDK 25."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import secrets
import signal
import subprocess
import sys
import tempfile
import time

OUTPUT_LIMIT = 65536
COMPILE_TIMEOUT = 5


class GraderError(Exception):
    """An operator/configuration failure, never a wrong student answer."""


def _run(command, cwd, timeout):
    try:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as exc:
        raise GraderError("Required grading executable is unavailable") from exc
    output = bytearray()
    reason = None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = OUTPUT_LIMIT - len(output)
                    output.extend(chunk[:room])
                    if len(chunk) > room:
                        reason = "output_limit"
                        break
                if reason:
                    break
            if reason is None:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
    finally:
        # Clean up children too, including processes retaining a stdout handle.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
    text = bytes(output).decode("utf-8", errors="replace")
    text = text.encode("utf-8")[:OUTPUT_LIMIT].decode("utf-8", errors="ignore")
    return process.returncode, text, reason


def _names(config, key):
    names = config.get(key)
    if not isinstance(names, list) or not names or len(names) > 64:
        raise GraderError("Source and test file lists must be nonempty")
    for name in names:
        if not isinstance(name, str) or len(name) > 512:
            raise GraderError("Invalid Java file name")
        parts = PurePosixPath(name).parts
        if (not parts or PurePosixPath(name).is_absolute() or "\\" in name
                or any(part in (".", "..") or part.startswith(".") for part in parts)
                or "/".join(parts) != name or not name.endswith(".java")):
            raise GraderError("Invalid Java file path")
    if len(set(names)) != len(names):
        raise GraderError("Duplicate Java file")
    return names


def _files(root, names):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Missing source directory")
    files = []
    for name in names:
        path = root
        for part in PurePosixPath(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("Symlink source is forbidden")
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("Missing or oversized Java file")
        files.append(str(path.resolve()))
    return files


def _invalid(message, output=""):
    return {"gradable": False, "format_errors": message, "output": output}


JAVA_NAME = r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"
FIELD_TYPE = r"(?:\[*[BCDFIJSZ]|\[*L[A-Za-z_$][A-Za-z0-9_$]*(?:/[A-Za-z_$][A-Za-z0-9_$]*)*;)"
METHOD_DESCRIPTOR = re.compile(r"\(" + FIELD_TYPE + r"*\)(?:V|" + FIELD_TYPE + r")")


def _required_methods(config):
    methods = config.get("requiredMethods")
    if not isinstance(methods, list) or not 1 <= len(methods) <= 64:
        raise GraderError("Declare the required public Java API")
    for method in methods:
        if (not isinstance(method, dict) or set(method) != {"className", "methodName", "descriptor", "static"}
                or not isinstance(method["className"], str) or not re.fullmatch(JAVA_NAME, method["className"])
                or not isinstance(method["methodName"], str) or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", method["methodName"])
                or not isinstance(method["descriptor"], str) or len(method["descriptor"]) > 4096
                or not METHOD_DESCRIPTOR.fullmatch(method["descriptor"])
                or type(method["static"]) is not bool):
            raise GraderError("Invalid required public Java API")
    return methods


def _api_probe(name, methods):
    # Class.forName(false) and getMethod inspect the API without initializing
    # student classes or calling their code. JVM descriptors preserve overloads.
    statements = []
    for method in methods:
        classname, methodname, descriptor = (json.dumps(method[key]) for key in ("className", "methodName", "descriptor"))
        expected_static = "true" if method["static"] else "false"
        statements.append("{" +
            f"Class<?> c = Class.forName({classname}, false, loader);" +
            f"var t = java.lang.invoke.MethodType.fromMethodDescriptorString({descriptor}, loader);" +
            f"var m = c.getMethod({methodname}, t.parameterArray());" +
            f"if (m.getReturnType() != t.returnType() || java.lang.reflect.Modifier.isStatic(m.getModifiers()) != {expected_static}) System.exit(1);" + "}")
    return (f"public final class {name} {{ public static void main(String[] args) {{" +
            "try { var loader = ClassLoader.getSystemClassLoader();" + "".join(statements) +
            "} catch (ReflectiveOperationException | LinkageError | TypeNotPresentException e) { System.exit(1); } } }")


def grade(job_dir: Path) -> dict:
    job = Path(job_dir).absolute()
    config_path = job / "tests/grading.json"
    try:
        if config_path.is_symlink() or config_path.stat().st_size > 65536:
            raise ValueError("Invalid grading configuration file")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Invalid grading configuration")
    except (OSError, ValueError) as exc:
        raise GraderError("Missing or invalid grading configuration") from exc
    methods = _required_methods(config)
    source_names = _names(config, "sourceFiles")
    test_names = _names(config, "testFiles")
    main = config.get("mainClass")
    if not isinstance(main, str) or not re.fullmatch(
            r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", main):
        raise GraderError("Invalid test main class")
    timeout = config.get("runTimeoutSeconds", 10)
    if type(timeout) not in (int, float) or not 0 < timeout <= 10:
        raise GraderError("Test timeout must be in (0, 10] seconds")
    try:
        tests = _files(job / "tests", test_names)
    except ValueError as exc:
        raise GraderError("Missing or unsafe instructor checks") from exc
    try:
        sources = _files(job / "student", source_names)
    except ValueError:
        return _invalid("Upload all required Java files as regular files.")
    code, output, reason = _run(["java", "-version"], job, 3)
    if code != 0 or reason or not re.search(r'version "25(?:[.\"+\-])', output):
        raise GraderError("The grader requires an actual JDK 25 runtime")
    with tempfile.TemporaryDirectory(prefix="java25-classes-") as directory:
        stage = Path(directory)
        student_classes, harness_classes = stage / "student", stage / "harness"
        student_classes.mkdir(); harness_classes.mkdir()
        probe_name = "_PL_API_" + secrets.token_hex(12)
        probe = stage / (probe_name + ".java")
        probe.write_text(_api_probe(probe_name, methods))
        compiler = ["javac", "--release", "25", "-encoding", "UTF-8", "-proc:none"]
        code, output, reason = _run(
            [*compiler, "-d", str(student_classes), "-sourcepath", "", *sources, str(probe)], job, COMPILE_TIMEOUT,
        )
        if code != 0 or reason:
            return _invalid("Your submission could not be compiled.", output)
        java = ["java", "-Xmx128m", "-XX:ActiveProcessorCount=2", "-XX:-UsePerfData"]
        code, output, reason = _run([*java, "-cp", str(student_classes), probe_name], job, 3)
        if code == 1 and not reason:
            return _invalid("The required public Java API does not match the task.")
        if code != 0 or reason:
            raise GraderError("Java API conformance check failed unexpectedly")
        marker = "PL_CHECKS_COMPLETED_" + secrets.token_hex(32)
        runner_name = "_PL_RUN_" + secrets.token_hex(12)
        runner = stage / (runner_name + ".java")
        runner.write_text(f'public final class {runner_name} {{ public static void main(String[] args) throws Exception {{ {main}.main(new String[0]); System.out.println("{marker}"); }} }}')
        code, output, reason = _run(
            [*compiler, "-cp", str(student_classes), "-d", str(harness_classes), "-sourcepath", "", *tests, str(runner)],
            job, COMPILE_TIMEOUT,
        )
        if code != 0 or reason:
            raise GraderError("Instructor checks could not be compiled")
        if not (harness_classes / (main.replace(".", "/") + ".class")).is_file():
            raise GraderError("Instructor test main class was not compiled")
        code, output, reason = _run(
            [*java, "-cp", os.pathsep.join([str(harness_classes), str(student_classes)]), runner_name], job, timeout,
        )
        completed = marker in output.splitlines()
        output = "\n".join(line for line in output.splitlines() if line != marker)
        if reason:
            return {"gradable": True, "score": 0, "output": output,
                    "timed_out": reason == "timeout", "output_limited": reason == "output_limit"}
        if code not in (0, 1):
            raise GraderError("Instructor checks terminated unexpectedly")
        if code == 0 and not completed:
            return {"gradable": True, "score": 0, "output": "The checks did not finish."}
        return {"gradable": True, "score": 1 if code == 0 else 0, "output": output}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, default=Path("/grade"))
    args = parser.parse_args()
    status = 0
    try:
        result = grade(args.job_dir)
    except GraderError as exc:
        print(f"Grader failure: {exc}", file=sys.stderr)
        result = {"gradable": False, "grading_error": True,
                  "format_errors": "Grader failure; contact your instructor.", "message": str(exc)}
        status = 2
    results = args.job_dir / "results"
    results.mkdir(exist_ok=True)
    path = results / "results.json"
    temporary = results / "results.json.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")
    temporary.replace(path)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
