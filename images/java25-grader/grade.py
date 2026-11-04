#!/usr/bin/env python3
"""One explicit JDK25/official JUnit runner for host and /grade jobs."""

import argparse
import functools
import errno
import stat
import zipfile
import zlib
import shutil
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import secrets
import signal
import subprocess
import sys
import tempfile
import time

OUTPUT_LIMIT = 65536


class GraderError(Exception):
    """An operator/configuration failure, never a wrong student answer."""


HARDENED_JDK = Path("/usr/lib/jvm/java-25-openjdk-amd64")
BUILD_JDK = Path("/opt/native-jdk")
MANAGEMENT_MEMBERS = (
    "lib/libmanagement.so",
    "lib/libmanagement_ext.so",
    "lib/libmanagement_agent.so",
)


def _validate_role_records(roles, owner_uids, owner_gids):
    if set(roles) != {"sbuser", "nativebuild"}:
        raise GraderError("Both fixed Java access roles are required")
    uids = set()
    gids = set()
    for role in roles.values():
        uid = role["uid"]
        gid = role["gid"]
        if (
            uid in {0, os.geteuid(), *owner_uids}
            or gid in {0, os.getegid(), *owner_gids}
            or uid in uids
            or gid in gids
            or role["groups"] != [gid]
        ):
            raise GraderError("Java roles are not isolated from owners/private groups")
        uids.add(uid)
        gids.add(gid)


def _role_records():
    import pwd, grp

    try:
        roles = {
            name: {
                "uid": p.pw_uid,
                "gid": p.pw_gid,
                "groups": sorted(set(os.getgrouplist(name, p.pw_gid))),
            }
            for name in ("sbuser", "nativebuild")
            for p in [pwd.getpwnam(name)]
        }
        build = pwd.getpwnam("nativebuild")
        group = grp.getgrnam("nativebuild")
        if (
            group.gr_gid != build.pw_gid
            or build.pw_shell not in ("/usr/sbin/nologin", "/sbin/nologin")
            or set(group.gr_mem) - {"nativebuild"}
        ):
            raise GraderError("Invalid private nativebuild account/group")
        _validate_role_records(roles, set(), set())
        return roles
    except (KeyError, OSError) as error:
        raise GraderError("Missing fixed Java access role") from error


def _protect_input_identity(job):
    import pwd, grp

    owners = {p.stat().st_uid for p in (job, job / "student", job / "tests")}
    groups = {p.stat().st_gid for p in (job, job / "student", job / "tests")}
    roles = _role_records()
    if not any(r["uid"] in owners or r["gid"] in groups for r in roles.values()):
        return
    if not Path("/.dockerenv").is_file():
        raise GraderError("Sandbox remapping requires supported container")
    for name in ("sbuser", "nativebuild"):
        role = roles[name]
        if role["gid"] in groups:
            allocated = {g.gr_gid for g in grp.getgrall()} | groups | {0, os.getegid()}
            gid = next((i for i in range(60000, 60100) if i not in allocated), None)
            group = grp.getgrgid(role["gid"])
            if gid is None or group.gr_name != name:
                raise GraderError("Cannot remap fixed private group")
            code, _, reason = _run(
                ["/usr/sbin/groupmod", "--gid", str(gid), name], job, 5
            )
            if code or reason:
                raise GraderError("Private group remap failed")
            code, _, reason = _run(
                ["/usr/sbin/usermod", "--gid", str(gid), name], job, 5
            )
            if code or reason:
                raise GraderError("Role group remap failed")
            if name == "nativebuild":
                for path in [BUILD_JDK, *BUILD_JDK.rglob("*")]:
                    info = path.lstat()
                    if (
                        info.st_uid != 0
                        or info.st_gid != role["gid"]
                        or stat.S_ISLNK(info.st_mode)
                    ):
                        raise GraderError(
                            "Unsafe build tree during private group remap"
                        )
                    os.chown(path, 0, gid, follow_symlinks=False)
        if role["uid"] in owners:
            allocated = (
                {entry.pw_uid for entry in pwd.getpwall()} | owners | {0, os.geteuid()}
            )
            uid = next((i for i in range(60000, 60100) if i not in allocated), None)
            if uid is None:
                raise GraderError("No isolated Java role UID")
            code, _, reason = _run(
                ["/usr/sbin/usermod", "--uid", str(uid), name], job, 5
            )
            if code or reason:
                raise GraderError("Java role UID remap failed")
        roles = _role_records()
    _validate_role_records(roles, owners, groups)


def _grading_environment():
    home = (
        str(HARDENED_JDK)
        if os.environ.get("PL_CONTAINMENT") == "official"
        else str(Path(shutil.which("java") or "/missing/java").resolve().parent.parent)
    )
    return {
        "PATH": home + "/bin:/usr/bin:/bin",
        "JAVA_HOME": home,
        "HOME": "/nonexistent",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _grading_java():
    return (
        str(HARDENED_JDK / "bin/java")
        if os.environ.get("PL_CONTAINMENT") == "official"
        else "java"
    )


def _validate_build_root_record(record, gid):
    if record != {"uid": 0, "gid": gid, "mode": 0o750, "directory": True}:
        raise GraderError("Complete build JDK root is not private to nativebuild")




def _build_process_records(proc, uid):
    records = {}
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = {
                line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                for line in (path / "status").read_text().splitlines()
                if ":" in line
            }
            ids = list(map(int, fields["Uid"].split()))
            if uid not in ids:
                continue
            if ids != [uid] * 4:
                raise GraderError("Unexpected build process UID transition")
            tail = (path / "stat").read_text().rsplit(")", 1)[1].split()
            records[int(path.name)] = {
                "uid": uid,
                "starttime": tail[19],
                "state": tail[0],
            }
        except FileNotFoundError:
            continue
    return records


def _enable_build_reaper():
    import ctypes

    if not Path("/.dockerenv").is_file() or os.geteuid() != 0:
        raise GraderError("Build cleanup requires supported namespace supervisor")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise GraderError("Cannot establish build descendant reaping")


def _finish_build_role(uid):
    if not Path("/.dockerenv").is_file() or os.geteuid() != 0:
        raise GraderError("Build cleanup requires container namespace supervisor")
    deadline = time.monotonic() + 3
    terminated = []
    reaped = []
    while True:
        records = _build_process_records(Path("/proc"), uid)
        if not records:
            return {
                "uid": uid,
                "remaining": [],
                "terminated": sorted(set(terminated)),
                "reaped": sorted(set(reaped)),
            }
        for pid, record in records.items():
            if pid <= 1 or pid == os.getpid():
                raise GraderError("Unsafe build cleanup PID")
            if _build_process_records(Path("/proc"), uid).get(pid) != record:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
                terminated.append(pid)
            except ProcessLookupError:
                pass
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if not pid:
                    break
                reaped.append(pid)
            except ChildProcessError:
                break
        if time.monotonic() >= deadline:
            raise GraderError("Build-role process remains before private grading")
        time.sleep(0.02)


def _hardened_tool_state():
    for parent in [HARDENED_JDK, *HARDENED_JDK.parents]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o7022:
            raise GraderError("Unsafe hardened JDK path")
    for name in MANAGEMENT_MEMBERS:
        if os.path.lexists(HARDENED_JDK / name):
            raise GraderError("Management restored to private grading JDK")



def _grading_boundary_unchecked():
    if not Path("/.dockerenv").is_file() or os.geteuid() != 0:
        raise GraderError("Java role boundary requires container namespace supervisor")
    roles = _role_records()
    root = BUILD_JDK.lstat()
    _validate_build_root_record(
        dict(
            uid=root.st_uid,
            gid=root.st_gid,
            mode=stat.S_IMODE(root.st_mode),
            directory=stat.S_ISDIR(root.st_mode),
        ),
        roles["nativebuild"]["gid"],
    )
    if _build_process_records(Path("/proc"), roles["nativebuild"]["uid"]):
        raise GraderError("Live build role at private grading boundary")
    prefix = [
        "/usr/sbin/runuser",
        "--preserve-environment",
        "-u",
        "sbuser",
        "--",
        "/usr/local/bin/landlock_sandbox",
    ]
    for flag, path in [
        ("-r", BUILD_JDK / "bin/java"),
        ("-x", BUILD_JDK / "bin/java"),
        *[("-r", BUILD_JDK / n) for n in MANAGEMENT_MEMBERS],
    ]:
        code, _, reason = _run_unchecked(
            [*prefix, "/usr/bin/test", flag, str(path)],
            Path("/tmp"),
            5,
            1024,
            env=_grading_environment(),
        )
        if code != 1 or reason:
            raise GraderError("Grading role can access complete build JDK")
    return {"roles": roles}


def _grading_boundary():
    try:
        return _grading_boundary_unchecked()
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise GraderError("Missing or invalid Java role/toolchain boundary") from error


def _child_file_limit():
    # Denied /proc makes JDK jspawnhelper close descriptors up to the hard
    # limit. Bound that work before Landlock, without granting new filesystem
    # access or changing the host supervisor's limit.
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    hard = 4096 if hard == resource.RLIM_INFINITY else min(hard, 4096)
    soft = hard if soft == resource.RLIM_INFINITY else min(soft, hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def _run_unchecked(command, cwd, timeout, output_limit=OUTPUT_LIMIT, *, env=None):
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=_child_file_limit,
            env=(
                {**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
                if env is None
                else env
            ),
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
                    room = output_limit - len(output)
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
    text = text.encode("utf-8")[:output_limit].decode("utf-8", errors="ignore")
    return process.returncode, text, reason


def _run(command, cwd, timeout, output_limit=OUTPUT_LIMIT, *, env=None):
    official = os.environ.get("PL_CONTAINMENT") == "official"
    return _run_unchecked(
        command,
        cwd,
        timeout,
        output_limit,
        env=(_grading_environment() if official and env is None else env),
    )


def _names(config, key):
    names = config.get(key)
    if not isinstance(names, list) or not names or len(names) > 64:
        raise GraderError("Source and test file lists must be nonempty")
    for name in names:
        if not isinstance(name, str) or len(name) > 512:
            raise GraderError("Invalid Java file name")
        parts = PurePosixPath(name).parts
        if (
            not parts
            or PurePosixPath(name).is_absolute()
            or "\\" in name
            or any(part in (".", "..") or part.startswith(".") for part in parts)
            or "/".join(parts) != name
            or not name.endswith(".java")
        ):
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


def _primary_files(job, config):
    """Необязательность допускает отсутствие, но не unsafe/oversized primary."""
    root = job / "student"
    names = _names(config, "sourceFiles")
    if config.get("additionalJavaSources", {}).get("primaryRequired", True):
        return _files(root, names)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe student directory")
    present = []
    for name in names:
        path = root
        for part in PurePosixPath(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("Symlink source is forbidden")
            if path.exists() and path != root / name and not path.is_dir():
                raise ValueError("Unsafe source parent")
        if path.exists():
            present.extend(_files(root, [name]))
    return present


PLATFORM = Path(__file__).resolve().parents[2]


def preflight(runtime, registry=None):
    return _preflight(runtime, registry)


def _preflight(runtime, registry):
    try:
        registry = registry if registry is not None else json.loads((PLATFORM / "runtime-profiles.json").read_text())
        profile = registry["profiles"][runtime]
        bundle = PLATFORM / profile["bundle"]
        if profile.get("assertionFeedbackProtocol") != 2:
            raise GraderError("Assertion feedback protocol mismatch")
        code, output, reason = _run([_grading_java(), "-version"], PLATFORM, 5)
        if code or reason or not re.search(r'version "25(?:[.\"+\-])', output):
            raise GraderError("The grader requires an actual JDK 25 runtime")
        return profile, bundle, output.strip()
    except (KeyError, OSError, ValueError) as error:
        raise GraderError("Missing or invalid runtime configuration") from error



def _files_any(root, name):
    p = PurePosixPath(name)
    if (
        p.is_absolute()
        or "\\" in name
        or not p.parts
        or any(x in (".", "..") for x in name.split("/"))
    ):
        raise GraderError("Unsafe runtime path")
    current = root
    if current.is_symlink():
        raise GraderError("Symlink runtime bundle")
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise GraderError("Symlink runtime file")
    if not current.is_file():
        raise GraderError("Missing runtime file")
    return current


def _compiled_class_names(root):
    # javac writes actual binary names into this fresh private output directory.
    # Enumerating paths neither loads classes nor runs static initializers.
    return {
        ".".join(path.relative_to(root).with_suffix("").parts)
        for path in root.rglob("*.class")
    }


def _source_classes(files):
    names = []
    for f in files:
        text = Path(f).read_text(encoding="utf-8")
        package = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
        names.append((package[1] + "." if package else "") + Path(f).stem)
    return names


def _invalid(message, output="", classification="student-compilation-failure"):
    return {
        "gradable": classification == "student-compilation-failure",
        **({"score": 0} if classification == "student-compilation-failure" else {}),
        "dependentExecution": "not-run",
        "format_errors": message,
        "output": output,
        "classification": classification,
        "studentCompilation": "failure",
        "trustedCompilation": "not-run",
        "infrastructure": "complete",
    }


@functools.cache
def _junit_result_helpers():
    import runpy

    return runpy.run_path(str(PLATFORM / "runtime/junit_result.py"))


def _unique_json_object(pairs):
    return _junit_result_helpers()["unique_json_object"](pairs)


def _validate_junit_counts(counts, require_cases=True):
    try:
        _junit_result_helpers()["validate_counts"](counts, require_cases=require_cases)
    except ValueError as error:
        raise GraderError(str(error)) from error


def _score(raw, counts, policy):
    mode = policy.get("mode")
    if mode == "weighted":
        return counts["passed"] / counts["executed"]
    if mode == "all-pass":
        return float(
            counts["failed"] == 0
            and counts["aborted"] == 0
            and counts["skipped"] == 0
            and counts["executed"] > 0
        )
    outcomes = counts["outcomes"]
    if mode == "contract-groups":
        groups = policy["groups"]
        total = sum(g["weight"] for g in groups)
        if total <= 0:
            raise GraderError("Scoring groups require positive total weight")
        if any(t not in outcomes for g in groups for t in g["tests"]):
            raise GraderError("Scoring group references missing stable test ID")
        return (
            sum(
                g["weight"]
                for g in groups
                if all(outcomes[t] == "successful" for t in g["tests"])
            )
            / total
        )
    if mode == "threshold":
        value = raw["score"] if policy["basis"] == "score" else counts["passed"]
        return float(value >= policy["value"])
    raise GraderError("Unknown scoring policy")


def validate_config(config):
    allowed = {
        "schemaVersion",
        "sourceFiles",
        "testFiles",
        "mode",
        "runtime",
        "java",
        "limits",
        "scoring",
        "discovery",
        "variants",
        "apiPrecheck",
        "additionalJavaSources",
        "publicCases",
        "feedback",
        "javaBuild",
    }
    if (
        not isinstance(config, dict)
        or set(config) - allowed
        or config.get("schemaVersion") != 1
    ):
        raise GraderError("Expected closed schemaVersion1 JUnit grading descriptor")
    native = config.get("runtime") == "java25-gradle-junit-v1"
    if native != ("javaBuild" in config):
        raise GraderError("Native runtime and javaBuild must be selected together")
    if native:
        build = config["javaBuild"]
        if (
            config.get("mode") != "implementation"
            or not isinstance(build, dict)
            or set(build)
            not in ({"kind", "artifact"}, {"kind", "mainClass", "artifact"})
            or build["kind"] != "gradle-jar-v1"
            or (
                "mainClass" in build
                and (
                    not isinstance(build["mainClass"], str)
                    or not re.fullmatch(
                        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*",
                        build["mainClass"],
                    )
                )
            )
            or not isinstance(build["artifact"], str)
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.jar", build["artifact"]
            )
        ):
            raise GraderError("Invalid closed native Java build record")
    if config.get("mode") not in ("implementation", "student-tests"):
        raise GraderError("Invalid submission mode")
    if "apiPrecheck" in config:
        api = config["apiPrecheck"]
        if (
            config["mode"] != "implementation"
            or not isinstance(api, dict)
            or set(api) != {"files", "entry"}
            or not isinstance(api["entry"], str)
            or not re.fullmatch(
                r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", api["entry"]
            )
        ):
            raise GraderError("Invalid Java API precheck")
        names = _names(api, "files")
        tests = _names(config, "testFiles")
        if not set(names) < set(tests):
            raise GraderError(
                "API precheck files must be a proper subset of trusted tests"
            )
    if "additionalJavaSources" in config:
        policy = config["additionalJavaSources"]
        caps = {
            "maxFiles": 128,
            "maxFileBytes": 1048576,
            "maxTotalBytes": 4194304,
            "maxArchiveBytes": 2097152,
        }
        if (
            config.get("runtime") not in ("java25-junit-v1", "java25-gradle-junit-v1")
            or config["mode"] != "implementation"
            or not isinstance(policy, dict)
            or set(policy) - {"archive", "primaryRequired", *caps}
            or not {"archive", *caps} <= set(policy)
            or (
                "primaryRequired" in policy
                and type(policy["primaryRequired"]) is not bool
            )
            or not isinstance(policy["archive"], str)
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.zip", policy["archive"]
            )
            or any(
                type(policy[k]) is not int or not 1 <= policy[k] <= limit
                for k, limit in caps.items()
            )
        ):
            raise GraderError("Invalid closed additional Java sources policy")
        reserved = [
            *_names(config, "sourceFiles"),
            *_names(config, "testFiles"),
            "grading-job.json",
            "tests/grading-job.json",
        ]
        if any(_path_collision(policy["archive"], name) for name in reserved):
            raise GraderError(
                "Additional Java archive conflicts with a declared/private path"
            )
    java = config.get("java", {})
    if (
        set(java) - {"release", "encoding", "compiler-options"}
        or java.get("release") != 25
        or java.get("encoding") != "UTF-8"
    ):
        raise GraderError("Java25 UTF-8 is required")
    opts = java.get("compiler-options", [])
    if opts != ["-proc:none", "-Xmaxerrs", "5"]:
        raise GraderError(
            "Unsupported compiler options; annotation processing is forbidden"
        )
    limits = config.get("limits", {})
    if (
        set(limits)
        - {
            "outer-seconds",
            "compile-seconds",
            "run-seconds",
            "max-output-bytes",
            "networking",
        }
        or limits.get("networking") is not False
    ):
        raise GraderError("Invalid offline limits")
    for name, default in [
        ("outer-seconds", 30),
        ("compile-seconds", 15),
        ("run-seconds", 10),
        ("max-output-bytes", 65536),
    ]:
        value = limits.get(name, default)
        if type(value) not in (int, float) or value <= 0:
            raise GraderError("Limits must be positive numbers")
    if limits.get("compile-seconds", 15) > limits.get(
        "outer-seconds", 30
    ) or limits.get("run-seconds", 10) > limits.get("outer-seconds", 30):
        raise GraderError("Inner limit exceeds outer limit")
    if (
        type(limits.get("max-output-bytes", 65536)) is not int
        or limits.get("max-output-bytes", 65536) > 65536
    ):
        raise GraderError("Maximum output limit is 65536")
    scoring = config.get("scoring", {})
    mode = scoring.get("mode")
    fields = {
        "weighted": {"mode"},
        "all-pass": {"mode"},
        "contract-groups": {"mode", "groups"},
        "threshold": {"mode", "basis", "value"},
    }
    if mode not in fields or set(scoring) != fields[mode]:
        raise GraderError("Invalid closed scoring policy")
    if mode == "threshold" and (
        scoring["basis"] not in ("score", "passed-tests")
        or type(scoring["value"]) not in (int, float)
        or scoring["value"] < 0
    ):
        raise GraderError("Invalid threshold")
    if mode == "contract-groups":
        if not isinstance(scoring["groups"], list) or not scoring["groups"]:
            raise GraderError("Missing groups")
        ids = set()
        for g in scoring["groups"]:
            if (
                set(g) != {"id", "weight", "tests"}
                or g["id"] in ids
                or type(g["weight"]) not in (int, float)
                or g["weight"] <= 0
                or not isinstance(g["tests"], list)
                or not g["tests"]
                or any(not isinstance(x, str) for x in g["tests"])
            ):
                raise GraderError("Invalid scoring group")
            ids.add(g["id"])
    discovery = config.get("discovery", {})
    if (
        set(discovery) != {"min-executed", "allow-skipped"}
        or type(discovery["min-executed"]) is not int
        or discovery["min-executed"] < 1
        or type(discovery["allow-skipped"]) is not bool
    ):
        raise GraderError("Invalid discovery policy")


# These affect only the compiler JVM, not Java source semantics or allowed author options.
COMPILER_JVM = ["java", "-XX:TieredStopAtLevel=1", "-XX:ActiveProcessorCount=2"]
COMPILER = [
    "com.sun.tools.javac.Main",
    "--release",
    "25",
    "-encoding",
    "UTF-8",
    "-proc:none",
    "-Xmaxerrs",
    "5",
    "-sourcepath",
    "",
]


class _JobRuntime:
    """Immutable libraries/official adapter compiled once, private to one job."""

    def __init__(self, root, bundle):
        self.root = root
        self.bundle = bundle
        self.adapter = root / "adapter"
        self.library_dir = root / "libs"
        self.adapter.mkdir()
        self.library_dir.mkdir()
        self.compiled = False
        self.observer = root / "observer"
        self.transformer = root / "transformer"
        self.junit = self.library_dir / "junit-platform-console-standalone-1.14.1.jar"
        self.compiler_archive = root / "compiler.jsa"
        for jar in bundle.glob("*.jar"):
            shutil.copyfile(jar, self.library_dir / jar.name)
        self.libs = os.pathsep.join(
            sorted(str(x) for x in self.library_dir.glob("*.jar"))
        )

    def compiler(self):
        # Only JDK javac classes are loaded: submitted code is parsed, never
        # executed (-proc:none). Generate cold within this job, never import an
        # author archive or reuse it across jobs/Java versions.
        option = (
            "SharedArchiveFile"
            if self.compiler_archive.is_file()
            else "ArchiveClassesAtExit"
        )
        return [
            _grading_java(),
            *COMPILER_JVM[1:],
            "-XX:" + option + "=" + str(self.compiler_archive),
            *COMPILER,
        ]

    def protect_archive(self):
        if self.compiler_archive.is_file():
            self.compiler_archive.chmod(0o600)

    def module_flags(self, module=None):
        return [
            "--module-path",
            os.pathsep.join(map(str, (module or self.observer, self.junit, self.library_dir / "json-simple-1.1.1.jar"))),
            "--add-modules",
            "org.prairielearn.feedback",
            "--add-reads",
            "org.prairielearn.feedback=ALL-UNNAMED",
        ]

    def runtime_libs(self):
        return os.pathsep.join(
            sorted(str(p) for p in self.library_dir.glob("*.jar") if p != self.junit)
        )

    def ensure_adapter(self, job, limits, durations, diagnostics):
        if self.compiled:
            durations["runnerCompilation"] = 0.0
            return
        self.observer.mkdir()
        self.transformer.mkdir()
        feedback = self.bundle / "feedback"
        for name, files, output, options in (
            (
                "observerCompilation",
                sorted((feedback / "module").rglob("*.java")),
                self.observer,
                [
                    "--module-path",
                    self.libs,
                    "-sourcepath",
                    str(feedback / "module"),
                ],
            ),
            (
                "transformerCompilation",
                [feedback / "Transform.java"],
                self.transformer,
                [],
            ),
        ):
            start = time.monotonic()
            code, text, reason = _run(
                [*self.compiler(), *options, "-d", str(output), *map(str, files)],
                job,
                limits.get("compile-seconds", 15),
                int(limits["max-output-bytes"]),
            )
            self.protect_archive()
            durations[name] = time.monotonic() - start
            diagnostics[name] = text.replace(str(job), "/grade").replace(
                str(self.root), "/runtime"
            )
            if code or reason:
                raise GraderError(
                    "Trusted assertion runtime compilation failed: " + diagnostics[name]
                )
        files = [
            str(self.bundle / "PlatformApiPrecheck.java"),
            *map(str, (self.bundle / "upstream").rglob("*.java")),
        ]
        start = time.monotonic()
        code, text, reason = _run(
            [
                *self.compiler(),
                *self.module_flags(),
                "-cp",
                self.runtime_libs(),
                "-d",
                str(self.adapter),
                *files,
            ],
            job,
            limits.get("compile-seconds", 15),
            int(limits["max-output-bytes"]),
        )
        self.protect_archive()
        durations["runnerCompilation"] = time.monotonic() - start
        diagnostics["runnerCompilation"] = text.replace(str(job), "/grade").replace(
            str(self.root), "/runtime"
        )
        if code or reason:
            raise GraderError(
                "Official JUnit adapter compilation failed: "
                + diagnostics["runnerCompilation"]
            )
        self.compiled = True
        if os.environ.get("PL_CONTAINMENT") == "official":
            self.root.chmod(0o711)
            for directory in (
                self.adapter,
                self.library_dir,
                self.observer,
                self.transformer,
            ):
                directory.chmod(0o755)
                for file in directory.rglob("*"):
                    file.chmod(0o755 if file.is_dir() else 0o644)

    def prepare_observer(
        self,
        job,
        config,
        stage,
        trusted,
        student,
        tests,
        limits,
        durations,
        diagnostics,
    ):
        """Sealed policy from fresh trusted compiler output; no student-written result."""
        module = stage / "observer"
        shutil.copytree(self.observer, module)
        cp = (
            os.pathsep.join(
                map(
                    str,
                    (
                        self.transformer,
                        self.junit,
                        self.adapter,
                        trusted,
                        student,
                        self.observer,
                    ),
                )
            )
            + os.pathsep
            + self.runtime_libs()
        )
        start = time.monotonic()

        def transform(*args):
            code, text, reason = _run(
                [
                    _grading_java(),
                    "-Xmx128m",
                    "-XX:TieredStopAtLevel=1",
                    "-XX:ActiveProcessorCount=2",
                    "-cp",
                    cp,
                    "Transform",
                    *map(str, args),
                ],
                job,
                limits.get("compile-seconds", 15),
                int(limits["max-output-bytes"]),
            )
            if code or reason:
                raise GraderError(
                    "Trusted assertion admission failed: "
                    + text.replace(str(stage), "/scratch")
                )

        facade = module / "org/prairielearn/feedback/Assertions.class"
        transform(
            trusted,
            facade,
            stage / "assertion-sites.properties",
        )
        transform(module, facade, stage / "adapter-sites.properties", "adapter")
        transform(
            "reader",
            module / "org/prairielearn/feedback/internal/State.class",
            stage / "reader-site.properties",
        )
        policy = "\n".join(
            (stage / name).read_text()
            for name in (
                "assertion-sites.properties",
                "adapter-sites.properties",
                "reader-site.properties",
            )
        )

        # Java Properties escaping is deliberately explicit for private absolute roots.
        def value(path):
            return (
                str(path).replace("\\", "\\\\").replace(":", "\\:").replace("=", "\\=")
            )

        policy += (
            "\nadapterRoot="
            + value(module.resolve())
            + "\ntrustedRoot="
            + value(trusted.resolve())
        )
        policy += "\nsnapshotBytes=32768\n"
        (module / "org/prairielearn/feedback/internal/policy.properties").write_text(
            policy
        )
        durations["trustedTransformation"] = time.monotonic() - start
        diagnostics["trustedTransformation"] = (
            "Trusted assertion feedback prepared"
        )
        return module


def _api_precheck(
    job, config, stage, student, files, runtime, limits, durations, diagnostics
):
    """Trusted Java API code executes with the same official containment as JUnit."""
    runtime.ensure_adapter(job, limits, durations, diagnostics)
    compiled = stage / "precheck"
    compiled.mkdir()
    start = time.monotonic()
    code, text, reason = _run(
        [
            *runtime.compiler(),
            "-cp",
            os.pathsep.join([runtime.libs, str(runtime.adapter)]),
            "-d",
            str(compiled),
            *files,
        ],
        job,
        limits.get("compile-seconds", 15),
        int(limits["max-output-bytes"]),
    )
    runtime.protect_archive()
    durations["apiCompilation"] = time.monotonic() - start
    diagnostics["apiCompilation"] = text.replace(str(job), "/grade").replace(
        str(stage), "/scratch"
    )
    if code or reason:
        raise GraderError(
            "API precheck compilation failed: "
            + (reason or diagnostics["apiCompilation"])
        )
    if _compiled_class_names(student) & _compiled_class_names(compiled):
        return (
            {
                "status": "unsafe",
                "message": "Классы решения конфликтуют с доверенными API-классами",
            },
            compiled,
            None,
        )
    output = stage / "api-results"
    output.mkdir()
    scratch = stage / "api-scratch"
    scratch.mkdir()
    params = stage / "api-params"
    params.mkdir()
    signature = secrets.token_hex(32)
    result_file = output / (secrets.token_hex(32) + ".json")
    parameter_file = params / "params.json"
    parameter_file.write_text(
        json.dumps(
            {
                "classes": str(student),
                "scratch": str(scratch),
                "entry": config["entry"],
                "signature": signature,
                "result_file": str(result_file),
            }
        )
    )
    prefix = []
    containment = "host-diagnostic"
    if os.environ.get("PL_CONTAINMENT") == "official":
        if (
            os.geteuid() != 0
            or not Path("/usr/local/bin/landlock_sandbox").is_file()
            or not shutil.which("runuser")
        ):
            raise GraderError("Official API precheck containment prerequisites missing")
        _protect_input_identity(job)
        stage.chmod(0o711)
        for directory in (student, compiled, runtime.adapter, runtime.library_dir):
            directory.chmod(0o755)
            for file in directory.rglob("*"):
                file.chmod(0o755 if file.is_dir() else 0o644)
        for directory in (output, scratch, params):
            directory.chmod(0o777)
        parameter_file.chmod(0o644)
        job.chmod(0o711)
        for folder in ("student", "tests"):
            (job / folder).chmod(0o700)
        prefix = [
            "/usr/sbin/runuser",
            "--preserve-environment",
            "-u",
            "sbuser",
            "--",
            "/usr/local/bin/landlock_sandbox",
        ]
        containment = "official-landlock-sbuser"
    classpath = os.pathsep.join([str(runtime.adapter), runtime.libs, str(compiled)])
    start = time.monotonic()
    code, text, reason = _run(
        [
            *prefix,
            _grading_java(),
            "--add-exports=java.base/jdk.internal.misc=ALL-UNNAMED",
            "-Xmx128m",
            "-XX:TieredStopAtLevel=1",
            "-XX:ActiveProcessorCount=2",
            "-XX:-UsePerfData",
            "-XX:+DisableAttachMechanism",
            "--illegal-native-access=deny",
            "--sun-misc-unsafe-memory-access=deny",
            "-cp",
            classpath,
            "org.prairielearn.api.PlatformApiPrecheck",
            str(parameter_file),
        ],
        scratch,
        limits.get("run-seconds", 10),
        int(limits["max-output-bytes"]),
    )
    durations["apiExecution"] = time.monotonic() - start
    diagnostics["apiExecution"] = text.replace(str(stage), "/scratch")
    if code or reason:
        raise GraderError("API precheck execution failed: " + (reason or str(code)))
    try:
        value = json.loads(result_file.read_text())
        if value.pop("signature") != signature or value.get("status") not in (
            "success",
            "mismatch",
            "infrastructure",
        ):
            raise ValueError("Invalid API report")
    except (OSError, ValueError, KeyError) as error:
        raise GraderError("API precheck report missing or invalid") from error
    if value["status"] == "infrastructure":
        raise GraderError(
            "API precheck infrastructure failure: " + value.get("message", "")
        )
    return value, compiled, containment


def _execute(
    job,
    config,
    sources,
    tests,
    bundle,
    toolchain,
    runtime,
    student_tests=False,
    native_context=None,
):
    if student_tests != (config["mode"] == "student-tests"):
        raise GraderError(
            "Private execution mode differs from validated submission mode"
        )
    limits = config["limits"]
    durations = {}
    diagnostics = {}
    if native_context is not None:
        native_context.update(durations=durations, diagnostics=diagnostics)
    with tempfile.TemporaryDirectory(prefix="java25-junit-") as tmp:
        stage = Path(tmp)
        student = stage / "student"
        trusted = stage / "trusted"
        for d in (student, trusted):
            d.mkdir()
        adapter = runtime.adapter
        library_dir = runtime.library_dir
        libs = runtime.libs


        def compile_phase(name, files, output, classpath):
            start = time.monotonic()
            code, text, reason = _run(
                [*runtime.compiler(), "-cp", classpath, "-d", str(output), *files],
                job,
                limits.get("compile-seconds", 15),
                int(limits["max-output-bytes"]),
            )
            runtime.protect_archive()
            durations[name] = time.monotonic() - start
            diagnostics[name] = text.replace(str(job), "/grade").replace(
                str(stage), "/scratch"
            )
            return code, reason

        def unsafe(message):
            value = _invalid(message, classification="unsafe-submission")
            value.update(
                studentCompilation="success",
                trustedCompilation=(
                    "success" if "trustedCompilation" in durations else "not-run"
                ),
                dependentExecution="not-run",
                durations=durations,
                diagnostics=diagnostics,
                toolchain=toolchain,
            )
            if "apiPrecheck" in config:
                value["apiPrecheck"] = (
                    "success" if "apiExecution" in durations else "not-run"
                )
                if "apiExecution" in durations:
                    value["apiContainment"] = api_containment
            return value

        reserved = (
            "org.junit.",
            "org.prairielearn.",
            "org.json.",
            "java.",
            "javax.",
            "PlatformJUnitAdapter",
            "JUnitAutograder",
        )
        if student_tests:
            code, reason = compile_phase("trustedCompilation", tests, trusted, libs)
            if code or reason:
                raise GraderError(
                    "Trusted fixture compilation failed: "
                    + diagnostics["trustedCompilation"]
                )
            code, reason = compile_phase(
                "studentCompilation",
                sources,
                student,
                os.pathsep.join([libs, str(trusted)]),
            )
        else:
            # Native production has no external dependencies in the fixed recipe.
            # An empty directory also prevents javac's empty -cp from using cwd.
            production_classpath = (
                str(student) if config["runtime"] == NATIVE_RUNTIME else libs
            )
            if native_context is not None:
                proof, code, reason = native_context["build"](stage, durations, diagnostics)
                native_context.update(proof=proof)
            else:
                code, reason = compile_phase("studentCompilation", sources, student, production_classpath)
        if reason:
            raise GraderError("Student compilation infrastructure limit: " + reason)
        if code:
            value = _invalid(
                "Исходники текущей попытки не скомпилированы. Исправьте ошибки компилятора и повторите отправку.",
                diagnostics["studentCompilation"],
            )
            value.update(
                trustedCompilation="success" if student_tests else "not-run",
                durations=durations,
                diagnostics=diagnostics,
                toolchain=toolchain,
            )
            if "apiPrecheck" in config:
                value.update(apiPrecheck="not-run", dependentExecution="not-run")
            return value
        if native_context is not None:
            native_context.update(
                studentCompiled=True, durations=durations, diagnostics=diagnostics
            )
        if any(name.startswith(reserved) for name in _compiled_class_names(student)):
            return unsafe("Submitted classes collide with trusted namespaces")
        api_classes = None
        api_containment = None
        if "apiPrecheck" in config:
            selected = set(config["apiPrecheck"]["files"])
            api_files = [
                f
                for f in tests
                if Path(f).relative_to(job / "tests").as_posix() in selected
            ]
            value, api_classes, api_containment = _api_precheck(
                job,
                config["apiPrecheck"],
                stage,
                student,
                api_files,
                runtime,
                limits,
                durations,
                diagnostics,
            )
            if value["status"] == "unsafe":
                return unsafe(value["message"])
            if value["status"] == "mismatch":
                return {
                    "gradable": True,
                    "score": 0,
                    "classification": "student-api-mismatch",
                    "studentCompilation": "success",
                    "trustedCompilation": "not-run",
                    "apiPrecheck": "failure",
                    "dependentExecution": "not-run",
                    "infrastructure": "complete",
                    "apiDiagnostic": {
                        "expected": value["expected"],
                        "observed": value["observed"],
                    },
                    "message": value["message"]
                    + ". Зависимые unit-тесты не выполнены.",
                    "durations": durations,
                    "diagnostics": diagnostics,
                    "toolchain": toolchain,
                    "apiContainment": api_containment,
                }
            tests = [f for f in tests if f not in api_files]
        if not student_tests:
            code, reason = compile_phase(
                "trustedCompilation",
                tests,
                trusted,
                os.pathsep.join(
                    [
                        libs,
                        str(student),
                        *(
                            [str(api_classes), str(runtime.adapter)]
                            if api_classes
                            else []
                        ),
                    ]
                ),
            )
            if reason:
                raise GraderError(
                    "Trusted suite compilation infrastructure limit: " + reason
                )
            if code:
                # Preserve established phase fields for private operator diagnosis.
                # Native callers still pass through student_result in main().
                return {
                    "gradable": False,
                    "grading_error": True,
                    "classification": "infrastructure-failure",
                    "infrastructure": "failure",
                    "studentCompilation": "success",
                    "trustedCompilation": "failure",
                    "dependentExecution": "not-run",
                    "durations": durations,
                    "diagnostics": diagnostics,
                    "toolchain": toolchain,
                    "message": "Trusted suite compilation failed",
                }
        trusted_names = _compiled_class_names(trusted)
        if api_classes is not None:
            trusted_names |= _compiled_class_names(api_classes)
        if _compiled_class_names(student) & trusted_names:
            return unsafe("Submitted classes collide with trusted classes")
        if api_classes is None:
            runtime.ensure_adapter(job, limits, durations, diagnostics)
        observer = (
            runtime.prepare_observer(
                job,
                config,
                stage,
                trusted,
                student,
                tests,
                limits,
                durations,
                diagnostics,
            )
            if not student_tests
            else runtime.observer
        )
        reports = stage / "results"
        reports.mkdir()
        params = stage / "params"
        params.mkdir()
        feedbackfile = reports / "feedback.json"
        report_key = secrets.token_hex(32)
        parameter_file = params / "params.json"
        parameter_file.write_text(
            json.dumps(
                {
                    "feedback_file": str(feedbackfile),
                    "report_key": report_key,
                    "reports_dir": str(reports),
                    "test_classes": _source_classes(
                        sources if student_tests else tests
                    ),
                    "student_classes": sorted(_compiled_class_names(student)),
                    "student_classes_root": str(student.resolve()),
                    "submission_mode": config["mode"],
                    "public_cases": config.get("publicCases", []),
                    "observe_assertions": not student_tests,
                    **(
                        {"trusted_console_support_root": str(trusted.resolve())}
                        if "coursesupport.JavaProcess" in trusted_names
                        else {}
                    ),
                }
            )
        )
        containment = "host-diagnostic"
        prefix = []
        if os.environ.get("PL_CONTAINMENT") == "official":
            if (
                os.geteuid() != 0
                or not Path("/usr/local/bin/landlock_sandbox").is_file()
                or not shutil.which("runuser")
            ):
                raise GraderError(
                    "Official root supervisor/sbuser/Landlock prerequisites missing"
                )
            _protect_input_identity(job)
            # Preserve official UNIX boundaries: tests, source and runtime remain
            # private; compiled classpath is root-owned and only readable.
            stage.chmod(0o711)
            runtime.root.chmod(0o711)
            reports.chmod(0o777)
            params.chmod(0o777)
            for directory in (student, trusted, adapter, library_dir, observer):
                directory.chmod(0o755)
                for file in directory.rglob("*"):
                    file.chmod(0o755 if file.is_dir() else 0o644)
            parameter_file.chmod(0o644)
            job.chmod(0o711)
            for folder in ("student", "tests"):
                (job / folder).chmod(0o700)
            prefix = [
                "/usr/sbin/runuser",
                "--preserve-environment",
                "-u",
                "sbuser",
                "--",
                "/usr/local/bin/landlock_sandbox",
            ]
            containment = "official-landlock-sbuser"
        classpath = os.pathsep.join(
            [
                str(adapter),
                runtime.runtime_libs(),
                str(trusted),
                *([str(api_classes)] if api_classes else []),
                str(student),
            ]
        )
        command = [
            *prefix,
            _grading_java(),
            "-Xmx128m",
            "-XX:TieredStopAtLevel=1",
            "-XX:ActiveProcessorCount=2",
            "-XX:-UsePerfData",
            "-XX:+DisableAttachMechanism",
            "--illegal-native-access=deny",
            "--sun-misc-unsafe-memory-access=deny",
            *runtime.module_flags(observer),
            "-Djunit.jupiter.extensions.autodetection.enabled="
            + str(not student_tests).lower(),
            "-cp",
            classpath,
            "org.prairielearn.feedback.PlatformJUnitAdapter",
            str(parameter_file),
        ]
        start = time.monotonic()
        code, text, reason = _run(
            command, job, limits.get("run-seconds", 10), int(limits["max-output-bytes"])
        )
        durations["execution"] = time.monotonic() - start
        base = {
            "gradable": True,
            "studentCompilation": "success",
            "trustedCompilation": "success",
            "infrastructure": "complete",
            "durations": durations,
            "diagnostics": diagnostics,
            "toolchain": toolchain,
            "containment": containment,
            "scoring": config["scoring"],
            "output": text,
        }
        if api_classes is not None:
            base.update(
                apiPrecheck="success",
                dependentExecution="complete",
                apiContainment=api_containment,
            )
        if reason:
            raise GraderError(
                "Полный отчёт JUnit не получен: исполнитель остановлен (" + reason + ")"
            )
        if code != 0 or not feedbackfile.is_file():
            raise GraderError("JUnit execution did not produce complete reports")
        try:
            raw, counts = _junit_result_helpers()["read_junit_xml"](reports, feedbackfile, report_key=report_key)
        except (ValueError, OSError) as error:
            raise GraderError("Invalid JUnit XML report: " + str(error)) from error
        _validate_junit_counts(counts, require_cases=not student_tests)
        if counts.get("feedbackProtocolVersion") != (1 if student_tests else 2):
            raise GraderError(
                "Assertion feedback protocol differs from private execution mode"
            )
        # Internal observations remain available to private verification; main()
        # applies the student boundary before writing native RESULTS.
        if "infrastructure" in counts.get("failureKinds", {}).values():
            raise GraderError(
                "Trusted check raised an unexpected exception outside student code"
            )
        base.update(
            publicCaseObservations=counts.get("publicCaseObservations", []),
            rawResult=raw,
            reportFormat="junit-xml",
            counts=counts,
            maxPoints=counts["executed"],
            tests=(
                [
                    {
                        "name": case["name"],
                        "description": "",
                        "message": "",
                        "output": "",
                        "points": int(case["status"] == "passed"),
                        "max_points": 1,
                    }
                    for case in counts["cases"]
                ]
                if not student_tests
                else raw["tests"]
            ),
            message=raw.get("message", ""),
        )
        incomplete = (
            counts["executed"] < config["discovery"]["min-executed"]
            or counts["discovered"] == 0
            or counts["aborted"] > 0
            or counts["containerFailures"] > 0
            or counts["skipped"] > 0
        )
        if incomplete or not raw.get("gradable"):
            if not student_tests:
                raise GraderError("Trusted JUnit discovery/execution is incomplete")
            base.update(score=0, classification="student-test-quality-failure")
            return base
        kinds = set(counts.get("failureKinds", {}).values())
        if counts["failed"] and ("timeout" in kinds or "output-limit" in kinds):
            timed_out = "timeout" in kinds
            base.update(
                score=_score(raw, counts, config["scoring"]),
                classification=(
                    "student-timeout" if timed_out else "student-output-overflow"
                ),
                timed_out=timed_out,
                output_limited=not timed_out,
            )
        else:
            base.update(
                score=_score(raw, counts, config["scoring"]),
                classification=(
                    (
                        "student-runtime-failure"
                        if "runtime" in kinds
                        else "behavior-failure"
                    )
                    if counts["failed"]
                    else "success"
                ),
            )
        return base


NATIVE_RUNTIME = "java25-gradle-junit-v1"
NATIVE_RECIPE = (
    "runtime/gradle-jar-v1/build.gradle",
    "runtime/gradle-jar-v1/settings.gradle",
)


























def _admit_java_job():
    _hardened_tool_state()
    _grading_boundary()



def _verify_landlock_helper():
    path = Path("/usr/local/bin/landlock_sandbox")
    try:
        if path.resolve(strict=True) != path:
            raise GraderError("Unsafe installed Landlock helper path")
        for parent in path.parents:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o7022:
                raise GraderError("Unsafe installed Landlock helper parent")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o7022:
            raise GraderError("Unsafe installed Landlock helper identity")
        try:
            os.getxattr(path, "security.capability", follow_symlinks=False)
        except OSError as error:
            if error.errno not in (errno.ENODATA, errno.ENOTSUP):
                raise
        else:
            raise GraderError("File capabilities on installed Landlock helper")
    except OSError as error:
        raise GraderError("Installed Landlock helper is unavailable") from error



def _native_containment(job, private_paths):
    import pwd

    runuser = shutil.which("runuser")
    if (
        os.environ.get("PL_CONTAINMENT") != "official"
        or os.geteuid() != 0
        or not Path("/.dockerenv").is_file()
        or not Path("/usr/local/bin/landlock_sandbox").is_file()
        or not runuser
    ):
        raise GraderError("Gradle build requires official isolated containment")
    _verify_landlock_helper()
    if {p.name for p in Path("/sys/class/net").iterdir()} != {"lo"}:
        raise GraderError("Gradle build requires actual network isolation")
    _protect_input_identity(job)
    roles = _role_records()
    uid = roles["nativebuild"]["uid"]
    if uid == 0:
        raise GraderError("Privileged Gradle build is forbidden")
    job.chmod(0o711)
    for folder in ("student", "tests"):
        (job / folder).chmod(0o700)
    prefix = [
        runuser,
        "--preserve-environment",
        "-u",
        "nativebuild",
        "--",
        "/usr/local/bin/landlock_sandbox",
    ]
    # These are actual UID/readability checks, before the first Gradle child.
    code, text, reason = _run(
        [*prefix, "/usr/bin/id", "-u"],
        Path("/tmp"),
        5,
        1024,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
    )
    if code or reason or text.strip() != str(uid):
        raise GraderError("Gradle child UID was not verified")
    for path in private_paths:
        code, text, reason = _run(
            [*prefix, "/usr/bin/test", "-r", str(path)],
            Path("/tmp"),
            5,
            1024,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
        if code != 1 or reason:
            raise GraderError("Gradle child can access private grading inputs")
    return uid, prefix


def _native_build(job, config, sources, extra_names, stage, runtime, durations, diagnostics):
    build, limits = config["javaBuild"], config["limits"]
    if (job / "build").exists() or (job / "build").is_symlink():
        raise GraderError("Native artifact parent must be fresh")
    stage.chmod(0o700)
    runtime.root.chmod(0o700)
    canary = stage / "private-build-canary"
    canary.write_bytes(secrets.token_bytes(32))
    uid, prefix = _native_containment(job, [canary, job / "tests/grading-job.json", *map(Path, _files(job / "tests", config["testFiles"]))])
    _enable_build_reaper()
    if _build_process_records(Path("/proc"), uid):
        raise GraderError("Native build role is not fresh")
    private = job / ".native-build-private"
    private.mkdir(mode=0o700)
    os.chown(private, job.stat().st_uid, -1)
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="native-gradle-build-") as temporary:
        work = Path(temporary)
        work.chmod(0o1777)
        for name in ("home", "user-cache", "project-cache", "tmp"):
            folder = work / name
            folder.mkdir(mode=0o700)
            os.chown(folder, uid, -1)
        for source in sources:
            path = Path(source)
            name = extra_names.get(str(path)) or path.relative_to(job / "student").as_posix()
            target = work / "src" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            target.chmod(0o444)
        for name in NATIVE_RECIPE:
            target = work / Path(name).name
            target.write_bytes(_files_any(PLATFORM, name).read_bytes())
            target.chmod(0o444)
        (work / "native-config.json").write_text(json.dumps(build))
        (work / "native-config.json").chmod(0o444)
        (work / "gradle.properties").write_text("org.gradle.daemon=false\norg.gradle.workers.max=2\norg.gradle.java.installations.auto-download=false\norg.gradle.java.installations.auto-detect=false\norg.gradle.java.installations.paths=" + str(BUILD_JDK) + "\norg.gradle.jvmargs=-Xmx128m -XX:ActiveProcessorCount=2 -XX:-UsePerfData\n")
        environment = {"PATH": str(BUILD_JDK) + "/bin:/usr/bin:/bin", "JAVA_HOME": str(BUILD_JDK), "HOME": str(work / "home"), "GRADLE_USER_HOME": str(work / "user-cache"), "TMPDIR": str(work / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            code, text, reason = _run([*prefix, "/opt/gradle/bin/gradle", "--offline", "--no-daemon", "--console=plain", "--project-cache-dir", str(work / "project-cache"), "jar"], work, limits.get("compile-seconds", 15), int(limits["max-output-bytes"]), env=environment)
        finally:
            _finish_build_role(uid)
            _grading_boundary()
        durations["gradleBuild"] = durations["studentCompilation"] = time.monotonic() - start
        diagnostics["gradleBuild"] = diagnostics["studentCompilation"] = text.replace(str(work), "/build")
        (private / "gradle.log").write_text(text)
        (private / "gradle.log").chmod(0o600)
        os.chown(private / "gradle.log", job.stat().st_uid, -1)
        if reason:
            raise GraderError("Gradle compilation infrastructure limit: " + reason)
        if code:
            if ":compileJava FAILED" not in text:
                raise GraderError("Gradle build failed outside student compilation")
            return {"schemaVersion": 1, "kind": "gradle-jar-v1", "status": "not-run"}, code, None
        compiled = work / "build/classes/java/main"
        if not compiled.is_dir():
            raise GraderError("Gradle production output missing")
        for path in compiled.rglob("*"):
            if path.is_symlink():
                raise GraderError("Unsafe compiled production output")
            if path.is_file():
                target = stage / "student" / path.relative_to(compiled)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        relative = "build/libs/" + build["artifact"]
        artifact = _files_any(work, relative)
        size = artifact.stat().st_size
        if not 0 < size <= 64 * 1024 * 1024:
            raise GraderError("Invalid native artifact size")
        target = job / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(artifact.read_bytes())
        target.chmod(0o444)
    return {"schemaVersion": 1, "kind": "gradle-jar-v1", "status": "success", "artifact": {"path": relative, "bytes": size}, "durationSeconds": durations["gradleBuild"]}, 0, None



def _path_collision(left, right):
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


class _AdditionalSubmissionError(Exception):
    def __init__(self, message, classification="unsafe-submission"):
        self.classification = classification
        super().__init__(
            "ZIP дополнительных Java sources: "
            + message
            + ". Исправьте доставку или используйте ручную сдачу."
        )


def _additional_inventory(job, config):
    """Fully validate bounded bytes before creating any extracted source file."""
    policy = config.get("additionalJavaSources")
    if policy is None:
        return [], None
    root = job / "student"
    file = root / policy["archive"]
    if root.is_symlink() or not root.is_dir():
        raise _AdditionalSubmissionError("небезопасный каталог student")
    if not file.exists() and not file.is_symlink():
        return [], None
    if file.is_symlink() or not stat.S_ISREG(file.stat(follow_symlinks=False).st_mode):
        raise _AdditionalSubmissionError("архив должен быть обычным файлом без symlink")
    if file.stat().st_size > policy["maxArchiveBytes"]:
        raise _AdditionalSubmissionError("превышен maxArchiveBytes")
    reserved = [
        *(
            config["sourceFiles"]
            if policy.get("primaryRequired", True)
            else [
                Path(p).relative_to(root).as_posix()
                for p in _primary_files(job, config)
            ]
        ),
        *config["testFiles"],
        "grading-job.json",
        "tests/grading-job.json",
        policy["archive"],
    ]
    members = []
    names = {}
    total = 0
    try:
        with file.open("rb") as raw:
            archive_bytes = raw.read(policy["maxArchiveBytes"] + 1)
        if len(archive_bytes) > policy["maxArchiveBytes"]:
            raise _AdditionalSubmissionError("превышен maxArchiveBytes")
        import io

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > 256:
                raise _AdditionalSubmissionError("больше 256 записей ZIP")
            for info in entries:
                original = info.orig_filename
                directory = original.endswith("/")
                name = original[:-1] if directory else original
                parts = name.split("/")
                if (
                    original != info.filename
                    or not name
                    or "\\" in name
                    or name.startswith("/")
                    or re.match(r"^[A-Za-z]:", name)
                    or any(
                        not part or part in (".", "..") or part.startswith(".")
                        for part in parts
                    )
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    or len(parts) > 32
                    or len(name.encode("utf-8")) > 512
                ):
                    raise _AdditionalSubmissionError(
                        "недопустимый относительный путь " + repr(original)
                    )
                mode = stat.S_IFMT(info.external_attr >> 16)
                if info.flag_bits & 1 or info.compress_type not in (
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                ):
                    raise _AdditionalSubmissionError(
                        "encrypted/неподдерживаемая запись " + repr(name)
                    )
                if mode not in (0, stat.S_IFDIR if directory else stat.S_IFREG):
                    raise _AdditionalSubmissionError(
                        "symlink/специальный тип записи " + repr(name)
                    )
                if name in names:
                    raise _AdditionalSubmissionError("повтор пути " + repr(name))
                if any(
                    _path_collision(name, x)
                    and not (isdir and name.startswith(x + "/"))
                    and not (directory and x.startswith(name + "/"))
                    for x, isdir in names.items()
                ):
                    raise _AdditionalSubmissionError(
                        "конфликт file/directory путей " + repr(name)
                    )
                if any(
                    _path_collision(name, x)
                    and not (directory and x.startswith(name + "/"))
                    for x in reserved
                ):
                    raise _AdditionalSubmissionError(
                        "конфликт с основным/доверенным путём " + repr(name)
                    )
                names[name] = directory
                if directory:
                    if info.file_size:
                        raise _AdditionalSubmissionError(
                            "каталог с содержимым " + repr(name)
                        )
                    continue
                if not name.endswith(".java"):
                    raise _AdditionalSubmissionError(
                        "разрешены только .java: " + repr(name)
                    )
                if (
                    len(members) >= policy["maxFiles"]
                    or info.file_size > policy["maxFileBytes"]
                    or total + info.file_size > policy["maxTotalBytes"]
                ):
                    raise _AdditionalSubmissionError(
                        "превышен лимит количества/размера исходников"
                    )
                data = bytearray()
                with archive.open(info) as member:
                    while chunk := member.read(
                        min(65536, policy["maxFileBytes"] - len(data) + 1)
                    ):
                        data.extend(chunk)
                        if (
                            len(data) > policy["maxFileBytes"]
                            or total + len(data) > policy["maxTotalBytes"]
                        ):
                            raise _AdditionalSubmissionError(
                                "превышен фактический лимит bytes"
                            )
                if len(data) != info.file_size:
                    raise _AdditionalSubmissionError(
                        "размер записи не совпадает " + repr(name)
                    )
                try:
                    bytes(data).decode("utf-8")
                except UnicodeError as error:
                    raise _AdditionalSubmissionError(
                        "исходник не UTF-8: " + repr(name),
                        "student-compilation-failure",
                    ) from error
                total += len(data)
                members.append((name, bytes(data)))
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        UnicodeError,
        zlib.error,
        NotImplementedError,
        RuntimeError,
        ValueError,
        OSError,
    ) as error:
        raise _AdditionalSubmissionError(
            "повреждённый или неподдерживаемый архив (" + type(error).__name__ + ")"
        ) from error
    members.sort()
    return members, {
        "archive": policy["archive"],
        "files": [
            {
                "path": name,
                "bytes": len(data),
            }
            for name, data in members
        ],
    }


def grade(job_dir, registry=None):
    job = Path(job_dir).absolute()
    try:
        config = json.loads(_files_any(job, "tests/grading-job.json").read_text())
    except (OSError, ValueError) as error:
        raise GraderError("Missing or invalid grading configuration") from error
    validate_config(config)
    official = os.environ.get("PL_CONTAINMENT") == "official"
    if official:
        _protect_input_identity(job)
    if official:
        _admit_java_job()
    profile, bundle, toolchain = preflight(config["runtime"], registry)
    import runpy

    try:
        runpy.run_path(str(PLATFORM / "runtime/student_feedback.py"))[
            "validate_public_cases"
        ](config.get("publicCases", []))
    except ValueError as error:
        raise GraderError("Invalid public feedback policy") from error
    additional_evidence = None
    native_context = {} if config["runtime"] == NATIVE_RUNTIME else None

    def finish(value):
        if additional_evidence is not None:
            value["additionalSources"] = additional_evidence
        if native_context is not None:
            value["buildEvidence"] = native_context.get(
                "proof",
                {"schemaVersion": 1, "kind": "gradle-jar-v1", "status": "not-run"},
            )
        return value

    if profile["mode"] != config["mode"]:
        raise GraderError("Runtime mode mismatch")
    source_names = _names(config, "sourceFiles")
    test_names = _names(config, "testFiles")
    try:
        tests = _files(job / "tests", test_names)
    except ValueError as error:
        raise GraderError("Missing or unsafe trusted sources") from error
    try:
        sources = _primary_files(job, config)
    except ValueError:
        return finish(
            _invalid(
                "Представьте объявленные обычные Java-файлы без символических ссылок.",
                classification="unsafe-submission",
            )
        )
    try:
        additional, additional_evidence = _additional_inventory(job, config)
    except _AdditionalSubmissionError as error:
        result = _invalid(str(error), classification=error.classification)
        if "apiPrecheck" in config:
            result.update(apiPrecheck="not-run", dependentExecution="not-run")
        return finish(result)
    if not sources and not additional:
        return finish(
            _invalid(
                "Представьте хотя бы один Java source",
                classification="unsafe-submission",
            )
        )
    with tempfile.TemporaryDirectory(prefix="java25-job-runtime-") as runtime_dir:
        extra_root = Path(runtime_dir) / "additional-sources"
        if additional:
            extra_root.mkdir(mode=0o700)
        extra_names = {}
        for name, data in additional:
            target = extra_root / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open("xb") as output:
                target.chmod(0o600)
                output.write(data)
            sources.append(str(target))
            extra_names[str(target)] = name
        runtime = _JobRuntime(Path(runtime_dir), bundle)
        if native_context is not None:
            native_context["proof"] = {
                "schemaVersion": 1,
                "kind": "gradle-jar-v1",
                "status": "not-run",
            }
        if config["mode"] == "implementation":
            if native_context is not None:
                native_context["build"] = (
                    lambda stage, durations, diagnostics: _native_build(
                        job,
                        config,
                        sources,
                        extra_names,
                        stage,
                        runtime,
                        durations,
                        diagnostics,
                    )
                )
            try:
                return finish(
                    _execute(
                        job,
                        config,
                        sources,
                        tests,
                        bundle,
                        toolchain,
                        runtime,
                        native_context=native_context,
                    )
                )
            except (OSError, ValueError, KeyError, GraderError) as error:
                if native_context is None:
                    raise
                if native_context.get("proof", {}).get("status") != "success":
                    native_context["proof"] = {"schemaVersion": 1, "kind": "gradle-jar-v1",
                                               "status": "failure", "reason": "build"}
                stages = (
                    {
                        "studentCompilation": "success",
                        "trustedCompilation": "not-run",
                        "dependentExecution": "not-run",
                        "durations": native_context.get("durations", {}),
                        "diagnostics": native_context.get("diagnostics", {}),
                    }
                    if native_context.get("studentCompiled")
                    else {}
                )
                return finish(
                    {
                        "gradable": False,
                        "grading_error": True,
                        "classification": "infrastructure-failure",
                        "infrastructure": "failure",
                        "message": str(error),
                        **stages,
                    }
                )
        variants = config.get("variants")
        if (
            not isinstance(variants, dict)
            or set(variants) != {"correct", "mutants"}
            or not variants["correct"]
            or not variants["mutants"]
        ):
            raise GraderError("Mutation profile requires correct and mutant variants")
        observations = {}
        for kind in ("correct", "mutants"):
            for variant in variants[kind]:
                if not isinstance(variant, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]+", variant
                ):
                    raise GraderError("Invalid variant ID")
                selected = [
                    p
                    for p, n in zip(tests, test_names)
                    if n.startswith("variants/" + variant + "/")
                ]
                if not selected:
                    raise GraderError("Missing declared variant " + variant)
                observations[variant] = _execute(
                    job, config, sources, selected, bundle, toolchain, runtime, True
                )
                if (
                    not observations[variant].get("gradable")
                    or observations[variant].get("classification")
                    == "student-compilation-failure"
                ):
                    return finish(observations[variant])
        quality = any(
            r["classification"] == "student-test-quality-failure"
            for r in observations.values()
        )
        correct = all(observations[v].get("score") == 1 for v in variants["correct"])
        killed = all(
            observations[v].get("counts", {}).get("failed", 0) > 0
            for v in variants["mutants"]
        )
        accepted = sum(observations[v].get("score") == 1 for v in variants["correct"])
        rejected = sum(
            observations[v].get("counts", {}).get("failed", 0) > 0
            for v in variants["mutants"]
        )
        message = (
            (
                "Submission test quality failure: incomplete or disabled tests. "
                if quality
                else ""
            )
            + f"Correct implementations accepted: {accepted}/{len(variants['correct'])}; mutants rejected: {rejected}/{len(variants['mutants'])}. "
            + "Expected outcomes: tests must pass correct implementations and reject every mutant."
        )
        return finish(
            {
                "message": message,
                "gradable": True,
                "score": float(correct and killed and not quality),
                "maxPoints": len(observations),
                "classification": (
                    "student-test-quality-failure"
                    if quality
                    else ("success" if correct and killed else "behavior-failure")
                ),
                "studentCompilation": "success",
                "trustedCompilation": "success",
                "infrastructure": "complete",
                "variants": observations,
                "scoring": config["scoring"],
                "output": "",
            }
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", type=Path, default=Path("/grade"))
    parser.add_argument(
        "--verification",
        action="store_true",
        help="Private operator verification report; never native student feedback",
    )
    args = parser.parse_args()
    status = 0
    try:
        result = grade(args.job_dir)
    except GraderError as error:
        result = {
            "gradable": False,
            "grading_error": True,
            "classification": "infrastructure-failure",
            "infrastructure": "failure",
            "message": str(error),
        }
        status = 2
    if result.get("classification") == "infrastructure-failure" or result.get(
        "grading_error"
    ):
        status = 2
    if not args.verification:
        import runpy

        boundary = runpy.run_path(str(PLATFORM / "runtime/student_feedback.py"))[
            "student_result"
        ]
        try:
            descriptor = json.loads(
                _files_any(args.job_dir, "tests/grading-job.json").read_text()
            )
        except (OSError, ValueError):
            descriptor = {}
        result = boundary(result, descriptor)
    path = args.job_dir / "results"
    path.mkdir(exist_ok=True)
    path.chmod(0o777)
    tmp = path / "results.json.tmp"
    tmp.write_text(json.dumps(result))
    tmp.replace(path / "results.json")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
