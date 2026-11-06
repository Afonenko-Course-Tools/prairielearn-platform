"""Выбранные файлы → приватные /grade jobs → результаты исполнения."""

import base64
import binascii
import re
import functools
import io
import zipfile
import stat
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import secrets
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
TOOL_VERSION = "2.1.0"


class JobError(Exception):
    pass


class ProjectDefect(JobError):
    pass


class GradingJob(dict):
    """Serialized contract remains portable; private scratch is not identity."""

    root = None


def safe(root, name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or Path(name).is_absolute()
        or re.match(r"^[A-Za-z]:", name)
        or any(ord(c)<32 or ord(c)==127 for c in name)
        or any(p in ("", ".", "..") for p in name.split("/"))
    ):
        raise JobError("Unsafe relative path: " + repr(name))
    p = Path(root)
    if p.is_symlink():
        raise JobError("Symlink root")
    for part in name.split("/"):
        p = p / part
        if p.is_symlink():
            raise JobError("Symlink path: " + name)
    return p


@functools.cache
def _junit_result_helpers():
    import runpy

    return runpy.run_path(str(ROOT / "runtime/junit_result.py"))


def validate(name, value):
    if name == "grading-job":
        name = "grading-job-v3"
    try:
        jsonschema.Draft202012Validator(
            json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        ).validate(value)
        if name == "check-result" and value.get("runtime") in (
            "java25-junit-v1",
            "java25-gradle-junit-v1",
            "java25-mutation-v1",
        ):
            _junit_result_helpers()["validate_outcome"](
                value, student_tests=value["runtime"] == "java25-mutation-v1"
            )
    except (jsonschema.ValidationError, OSError, ValueError) as error:
        raise JobError(f"Invalid {name}: {error}") from error


def validate_profile(check):
    validate("project-check", check)


def inventory(manifest):
    validate("native-checks", manifest)
    selected = {}
    for project in manifest["projects"]:
        q = project["qualifiedId"]
        if q in selected:
            raise JobError("Duplicate selected check " + q)
        if project.get("check"):
            selected[q] = project
    return [selected[q] for q in sorted(selected)]


def load_runtime_registry():
    return json.loads((ROOT / "runtime-profiles.json").read_text())


def selected_bytes(item):
    try:
        data = base64.b64decode(item["data"], validate=True)
    except (ValueError, binascii.Error, KeyError, TypeError) as error:
        raise JobError("Invalid selected file bytes") from error
    if len(data) > 1048576:
        raise JobError("Selected file size limit")
    return data


def _selection(items):
    if not isinstance(items, list) or len(items) > 4096:
        raise JobError("Selected file count limit")
    names = set(); targets = set(); total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", "target", "data"}:
            raise JobError("Closed selected file required")
        name = item["name"]; target = item["target"]
        safe(Path("/selected"), name); safe(Path("/selected"), target)
        for value, seen in ((name, names), (target, targets)):
            if any(value == n or value.startswith(n + "/") or n.startswith(value + "/") for n in seen):
                raise JobError("Duplicate or colliding selected target")
            seen.add(value)
        total += len(selected_bytes(item))
        if total > 64 * 1024**2:
            raise JobError("Selected total size limit")
    return [dict(item) for item in items]


def _fixture_selection(items):
    if not isinstance(items,list) or len(items)>4096:
        raise JobError("Selected fixture count limit")
    selected={};total=0
    for item in items:
        row=_selection([item])[0];key=(row["target"],row["name"])
        data=selected_bytes(row)
        if key in selected:
            if selected_bytes(selected[key]) != data:
                raise JobError("Conflicting selected fixture bytes")
            continue
        total+=len(data)
        if total>64*1024**2:raise JobError("Selected fixture total size limit")
        selected[key]=row
    return list(selected.values())


def _cases(project):
    record = project.get("contractCases")
    if not record:
        raise JobError("Missing selected contract cases")
    _selection([record])
    try: cases = json.loads(selected_bytes(record))
    except (ValueError, UnicodeError) as error: raise JobError("Invalid contract cases JSON") from error
    validate("contract-cases", cases)
    if len({c["id"] for c in cases["cases"]}) != len(cases["cases"]):
        raise JobError("Duplicate contract case ID")
    return cases


def scenario_inventory(manifest, snapshot=None, ids=None):
    records = []
    for project in inventory(manifest):
        q = project["qualifiedId"]
        if ids is not None and q not in ids: continue
        records.append({"qualifiedId": q, "scenario": "starter", "optional": False})
        for ref in project["check"].get("references", []):
            records.append({"qualifiedId": q, "scenario": "reference:" + ref["name"], "optional": ref.get("optional", False)})
        if project["check"].get("contract-cases"):
            for case in _cases(project)["cases"]:
                records.append({"qualifiedId": q, "scenario": "contract:" + case["id"], "optional": False})
    return sorted(records, key=lambda row: (row["qualifiedId"], row["scenario"]))


def prepare_job(
    manifest, snapshot, id, scenario, scope="declared", delivery=None, registry=None
):
    projects = [p for p in inventory(manifest) if p["qualifiedId"] == id]
    if len(projects) != 1:
        raise JobError("ID is not in declared check inventory")
    p = projects[0]
    check = p["check"]
    try:
        validate_profile(check)
    except JobError as error:
        raise ProjectDefect(str(error)) from error
    sources = _selection(p.get("sources", []))
    tests = _selection(p.get("trustedTests", []))
    public = _selection(p.get("verificationTests", []))
    fixtures = _fixture_selection(p.get("contractFixtures", []))
    if p.get("readiness", {}).get("ready") is False or not sources or not tests:
        raise ProjectDefect("Selected project is incomplete: " + id)
    selected = sources
    extra_policy = check.get("additional-java-sources")
    archive_name = extra_policy["archive"] if extra_policy else None
    optional_primary = (
        extra_policy is not None and extra_policy.get("primary-required", True) is False
    )
    primary_names = {x["name"] for x in sources}
    generated_archive = None
    reference_source_names = None
    if archive_name:
        reserved = [
            *primary_names,
            *[x["name"] for x in [*tests, *public]],
            "grading-job.json",
            "tests/grading-job.json",
        ]
        if any(
            archive_name == name
            or archive_name.startswith(name + "/")
            or name.startswith(archive_name + "/")
            for name in reserved
        ):
            raise JobError(
                "Additional Java archive conflicts with primary/trusted path"
            )
    if scenario.startswith("reference:"):
        name = scenario.split(":", 1)[1]
        refs = [r for r in check.get("references", []) if r["name"] == name]
        if len(refs) != 1:
            raise JobError("Undeclared reference " + name)
        declared = [r for r in p.get("references", []) if r["name"] == name]
        if len(declared) != 1:
            raise JobError("Named reference inventory missing " + name)
        if not declared[0]["available"]:
            raise JobError("reference-unavailable:" + name)
        selected = _selection(declared[0].get("sources", []))
        reference_names = {x["name"] for x in selected}
        complete_java_reference = (
            not extra_policy
            and check["runtime"] in ("java25-junit-v1", "java25-gradle-junit-v1")
        )
        if complete_java_reference:
            # Только exact named reference; публичная student policy не меняется.
            contents = [selected_bytes(x) for x in selected]
            if (not selected or len(selected) > 128
                or any(not x["name"].endswith(".java") for x in selected)
                or any(len(data) > 1048576 for data in contents)
                or sum(len(data) for data in contents) > 4194304):
                raise JobError("Reference Java source count/type/size limit")
            reference_source_names = sorted(reference_names)
        elif (not extra_policy and reference_names != primary_names) or (
            not optional_primary and not primary_names <= reference_names
        ):
            raise JobError("Reference source mapping differs from student source names")
        extras = [
            x for x in selected if x["name"] not in primary_names
        ]
        if extras and not complete_java_reference:
            if any(not x["name"].endswith(".java") for x in extras):
                raise JobError("Reference extras must be Java sources")
            buffer = io.BytesIO()
            with zipfile.ZipFile(
                buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                for x in sorted(extras, key=lambda x: x["name"]):
                    info = zipfile.ZipInfo(
                        x["name"], date_time=(1980, 1, 1, 0, 0, 0)
                    )
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(
                        info, selected_bytes(x)
                    )
            generated_archive = buffer.getvalue()
    elif scenario.startswith("contract:"):
        path = check.get("contract-cases")
        if not path:
            raise JobError("No declared contract cases")
        cases = _cases(p)
        case = [c for c in cases["cases"] if c["id"] == scenario.split(":", 1)[1]]
        if len(case) != 1:
            raise JobError("Unknown contract case")
        replacements = {}
        for x in case[0]["sources"]:
            if not x["fixture"].startswith("tests/fixtures/") or x[
                "submission"
            ] not in primary_names | ({archive_name} if archive_name else set()):
                raise JobError("Unauthorized contract fixture/submission")
            bound = [f for f in fixtures if f["target"] == x["fixture"] and f["name"] == x["submission"]]
            if len(bound) != 1:
                raise JobError("Selected contract fixture missing/ambiguous")
            if x["submission"] in replacements:
                raise JobError("Duplicate fixture submission")
            replacements[x["submission"]] = dict(bound[0])
        selected = (
            list(replacements.values())
            if optional_primary
            else [replacements.get(x["name"], x) for x in sources]
        )
        if not optional_primary and archive_name in replacements:
            selected.append(replacements[archive_name])
    elif scenario != "starter":
        raise JobError("Unknown scenario")
    java = {
        "release": 25,
        "encoding": "UTF-8",
        "compiler-options": ["-proc:none", "-Xmaxerrs", "5"],
    }
    java.update(check.get("java", {}))
    limits = {
        "outer-seconds": 30,
        "compile-seconds": 15,
        "run-seconds": 10,
        "networking": False,
        "max-output-bytes": 65536,
    }
    limits.update(check.get("limits", {}))
    grading = {
        "schemaVersion": 1,
        "sourceFiles": [x["name"] for x in sources],
        "testFiles": [x["name"] for x in tests],
        "mode": check.get(
            "mode", check.get("sourceProfile", {}).get("mode", "implementation")
        ),
        "runtime": check["runtime"],
        "java": java,
        "limits": limits,
        "scoring": check.get("scoring", {"mode": "weighted"}),
        "discovery": {
            "min-executed": 1,
            "allow-skipped": False,
            **check.get("discovery", {}),
        },
    }

    def api_selection(field, selection):
        value = p.get(field)
        if value is None:
            return None
        names = {x["name"] for x in selection}
        declaration = check.get(
            "api-precheck" if field == "apiPrecheck" else "verification-api-precheck",
            {},
        )
        if (
            not isinstance(value, dict)
            or set(value) != {"files", "entry"}
            or not isinstance(value["files"], list)
            or not value["files"]
            or any(not isinstance(x, str) for x in value["files"])
            or len(set(value["files"])) != len(value["files"])
            or not set(value["files"]) < names
            or value["entry"] != declaration.get("entry")
        ):
            raise JobError(
                "API precheck is not a proper subset of selected trusted sources"
            )
        return dict(value, files=list(value["files"]))

    api = api_selection("apiPrecheck", tests)
    public_api = api_selection("verificationApiPrecheck", public)
    if api and public and not public_api:
        raise JobError(
            "Public fixed-API verification requires an explicit API precheck"
        )
    if bool(check.get("api-precheck")) != bool(api) or bool(
        check.get("verification-api-precheck")
    ) != bool(public_api):
        raise JobError("API precheck selection missing or undeclared")
    if api:
        grading["apiPrecheck"] = api
    if extra_policy:
        grading["additionalJavaSources"] = {
            **(
                {"primaryRequired": extra_policy["primary-required"]}
                if "primary-required" in extra_policy
                else {}
            ),
            **({"allowAdditional": extra_policy["allow-additional"]} if "allow-additional" in extra_policy else {}),
            "archive": archive_name,
            **{
                new: extra_policy[old]
                for old, new in [
                    ("max-files", "maxFiles"),
                    ("max-file-bytes", "maxFileBytes"),
                    ("max-total-bytes", "maxTotalBytes"),
                    ("max-archive-bytes", "maxArchiveBytes"),
                ]
            },
        }
    if "java-build" in check:
        build = check["java-build"]
        grading["javaBuild"] = {
            "kind": build["kind"],
            **({"mainClass": build["main-class"]} if "main-class" in build else {}),
            "artifact": build["artifact"],
        }
    if "variants" in check:
        grading["variants"] = check["variants"]
    runtime = (registry or load_runtime_registry())["profiles"][check["runtime"]]
    if check["runtime"] == "fish-git-v1":
        grading.pop("java")
    expectations = (
        case[0]["expected"]
        if scenario.startswith("contract:")
        else check.get("verification-expectations", {}).get(
            "reference" if scenario.startswith("reference:") else "starter", {}
        )
    )
    job = GradingJob(
        schemaVersion=3,
        scope=scope,
        qualifiedId=id,
        scenario=scenario,
        runtime=check["runtime"],
        imageDigest=runtime["image"] or os.environ.get("PL_LOCAL_IMAGE_ID"),
        sources=selected,
        trustedTests=tests,
        verificationTests=public,
        grading=grading,
        expectations=expectations,
    )
    if scope == "delivery":
        from delivery4 import code_ids
        from delivery_verification import file_bytes
        if not delivery or id not in code_ids({k:v for k,v in delivery.items() if k != "_root"}):
            raise JobError("ID absent from automatic delivery")
        native = Path(delivery.get("_root", ""))
        question = "questions/" + id + "/"
        info = json.loads(file_bytes(native, question + "info.json"))
        if info.get("externalGradingOptions", {}).get("image") != job["imageDigest"]:
            raise JobError("Exported runtime image differs from selected image")
        if json.loads(file_bytes(native, question + "tests/grading-job.json")) != grading:
            raise JobError("Exported grading descriptor differs from selected check")
        for rows, prefix in ((tests, "tests/"), (sources, "serverFilesQuestion/starter/")):
            for row in rows:
                if file_bytes(native, question + prefix + row["name"]) != selected_bytes(row):
                    raise JobError("Exported selected file differs from grading input")
    if reference_source_names is not None:
        # Exported student descriptor сравнен выше; это только private reference job.
        grading = dict(grading, sourceFiles=reference_source_names)
        job["grading"] = grading
    validate("grading-job", job)
    job.root = Path(tempfile.mkdtemp(prefix="grading-job-"))
    scratch = job.root.lstat()
    job._scratch = (job.root, scratch.st_dev, scratch.st_ino, os.getuid(), os.getgid(), job["imageDigest"])
    job._containers_stopped = False
    for folder, selection in [("student", selected), ("tests", tests)]:
        (job.root / folder).mkdir(exist_ok=True)
        for x in selection:
            if (
                folder == "student"
                and generated_archive is not None
                and x["name"] not in primary_names
            ):
                continue
            target = safe(job.root, folder + "/" + x["name"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(selected_bytes(x))
    if generated_archive is not None:
        safe(job.root, "student/" + archive_name).write_bytes(generated_archive)
    (job.root / "tests/grading-job.json").write_text(
        json.dumps(grading, sort_keys=True)
    )
    if public:
        publicroot = job.root / "public-verification"
        (publicroot / "student").mkdir(parents=True)
        (publicroot / "tests").mkdir()
        shutil.copytree(
            job.root / "student", publicroot / "student", dirs_exist_ok=True
        )
        for x in public:
            target = safe(publicroot, "tests/" + x["name"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(selected_bytes(x))
        cfg = dict(
            grading,
            testFiles=[x["name"] for x in public],
            scoring={"mode": "weighted"},
        )
        cfg.pop("apiPrecheck", None)
        if public_api:
            cfg["apiPrecheck"] = public_api
        (publicroot / "tests/grading-job.json").write_text(
            json.dumps(cfg, sort_keys=True)
        )
    return job


NATIVE_RUNTIME = "java25-gradle-junit-v1"




def _validate_build_observation(
    result, artifact=None
):
    proof = result.get("buildEvidence")
    if not isinstance(proof, dict):
        raise JobError("Native build evidence is missing")
    classification = result.get("classification")
    student = result.get("studentCompilation")
    trusted = result.get("trustedCompilation")
    api = result.get("apiPrecheck")
    dependent = result.get("dependentExecution")
    if student == "failure" and (
        classification not in ("student-compilation-failure", "unsafe-submission")
        or trusted != "not-run"
        or api not in (None, "not-run")
        or dependent not in (None, "not-run")
    ):
        raise JobError("Inconsistent native student compilation outcome")
    if classification == "student-compilation-failure" and student != "failure":
        raise JobError("Native compilation failure is missing its stage fact")
    if classification == "student-api-mismatch" and (
        student != "success"
        or trusted != "not-run"
        or api != "failure"
        or dependent != "not-run"
    ):
        raise JobError("Inconsistent native API mismatch outcome")
    if api == "failure" and classification != "student-api-mismatch":
        raise JobError("Native API failure cannot be a behavior outcome")
    if api == "not-run" and (
        classification not in ("student-compilation-failure", "unsafe-submission")
        or trusted != "not-run"
    ):
        raise JobError("Inconsistent native API not-run outcome")
    if api == "success" and student != "success":
        raise JobError("Successful native API check requires student compilation")
    behavior = classification in (
        "success",
        "behavior-failure",
        "student-runtime-failure",
        "student-timeout",
        "student-output-overflow",
        "student-test-quality-failure",
    )
    if behavior and (
        result.get("infrastructure") != "complete"
        or student != "success"
        or trusted != "success"
        or api in ("failure", "not-run")
        or dependent == "not-run"
    ):
        raise JobError(
            "Native behavior outcome requires completed compilation/API stages"
        )
    if dependent == "complete" and (student != "success" or trusted != "success"):
        raise JobError("Native execution cannot precede compilation")
    negative = classification in (
        "student-compilation-failure",
        "student-api-mismatch",
    ) or (classification == "unsafe-submission" and trusted == "not-run")
    if proof.get("status") == "not-run" and not negative:
        raise JobError("Native build not-run requires a compile/API negative outcome")
    if student == "failure" and proof.get("status") != "not-run":
        raise JobError("Compilation failure cannot claim a build")
    if (
        result.get("infrastructure") == "complete"
        and not negative
        and result.get("classification") != "unsafe-submission"
        and proof.get("status") != "success"
    ):
        raise JobError("Behavior observation requires successful native build")
    if proof.get("status") == "failure" and result.get("infrastructure") != "failure":
        raise JobError("Trusted build failure cannot be scored")
    if proof.get("status") == "success":
        if result.get("studentCompilation") != "success":
            raise JobError(
                "Successful native build requires successful student compilation"
            )
        if (
            artifact is not None
            and proof.get("artifact", {}).get("path") != "build/libs/" + artifact
        ):
            raise JobError("Build artifact differs from descriptor")
    return proof


def run_job(job, backend="host", registry=None):
    job._containers_stopped = False
    validate("grading-job", job)
    if not getattr(job, "root", None):
        raise JobError("Prepared private job root required")
    common = {
        k: job[k]
        for k in (
            "scope",
            "qualifiedId",
            "scenario",
            "runtime",
            "imageDigest",
        )
    }
    native = job["runtime"] == NATIVE_RUNTIME
    try:
        if backend == "host":
            profile = (registry or load_runtime_registry())["profiles"][job["runtime"]]
            spec = importlib.util.spec_from_file_location(
                "platform_grader",
                safe(ROOT, profile.get("runner", "images/java25-grader/grade.py")),
            )
            grader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(grader)
            try:
                result = (
                    grader.grade(job.root, registry=registry)
                    if registry is not None and job["runtime"] != "fish-git-v1"
                    else grader.grade(job.root)
                )
            except grader.GraderError as error:
                raise JobError(str(error)) from error
        elif backend == "container":
            if not job["imageDigest"]:
                raise JobError("Runtime production image has not been built/published")
            job.containerName = "plcheck-" + secrets.token_hex(12)
            cmd = [
                "docker",
                "run",
                "--rm",
                "--name",
                job.containerName,
                "--network",
                "none",
                "--cpus",
                "0.9",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--mount",
                f"type=bind,src={job.root},dst=/grade",
                job["imageDigest"],
                "--verification",
            ]
            try:
                p = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=job["grading"]["limits"]["outer-seconds"],
                )
            except subprocess.TimeoutExpired as error:
                cleanup = subprocess.run(
                    ["docker", "rm", "--force", job.containerName],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if cleanup.returncode and "No such container" not in cleanup.stderr:
                    raise JobError(
                        "Outer Docker timeout; container cleanup failed: "
                        + cleanup.stderr
                    ) from error
                job._containers_stopped = True
                raise JobError("Outer Docker timeout; container removed") from error
            if p.returncode not in (0, 2):
                raise JobError("Docker infrastructure failure: " + p.stderr)
            job._containers_stopped = True
            result = json.loads(
                (job.root / "results/results.json").read_text(),
                object_pairs_hook=_junit_result_helpers()["unique_json_object"],
            )
        else:
            raise JobError("Unknown backend")
    except (JobError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        result = {
            "infrastructure": "failure",
            "classification": "infrastructure-failure",
            "gradable": False,
            "grading_error": True,
            "message": str(error),
        }
    if native:
        if "buildEvidence" not in result and result.get("infrastructure") == "failure":
            result["buildEvidence"] = {
                "schemaVersion": 1,
                "kind": "gradle-jar-v1",
                "status": "failure",
                "reason": "configuration",
            }
        _validate_build_observation(
            result,
            job["grading"]["javaBuild"]["artifact"],
        )
    if (job.root / "public-verification").is_dir() and result.get(
        "infrastructure"
    ) == "complete":
        publicjob = GradingJob(job)
        publicjob.root = job.root / "public-verification"
        primary_stopped = job._containers_stopped
        job._containers_stopped = False
        try:
            publicresult = run_job(publicjob, backend, registry)
        finally:
            job._containers_stopped = primary_stopped and getattr(publicjob, "_containers_stopped", False)
        result["publicResult"] = {
            k: v
            for k, v in publicresult.items()
            if k
            not in {
                "schemaVersion",
                "scope",
                "qualifiedId",
                "scenario",
                            "runtime",
                "imageDigest",
                                "backend",
            }
        }
        if publicresult.get("infrastructure") != "complete":
            result = {
                "infrastructure": "failure",
                "classification": "infrastructure-failure",
                "gradable": False,
                "grading_error": True,
                "message": "Public verification infrastructure failed",
                "publicResult": result["publicResult"],
                **(
                    {
                        key: result[key]
                        for key in (
                            "buildEvidence",
                            "studentCompilation",
                            "trustedCompilation",
                            "apiPrecheck",
                            "dependentExecution",
                        )
                        if key in result
                    }
                    if native
                    else {}
                ),
            }
    if any(key in result and result[key] != value for key, value in common.items()):
        raise JobError("Runtime result attempted to replace trusted job bindings")
    value = {"schemaVersion": 1, "backend": backend, **common, **result}
    validate("check-result", value)
    return value


def cleanup_job(job, backend):
    """Удалить scratch; вернуть владельца только после остановки всех контейнеров."""
    try:
        shutil.rmtree(job.root)
        return
    except PermissionError:
        if backend != "container":
            raise
    prepared = getattr(job, "_scratch", None)
    if not prepared or not getattr(job, "_containers_stopped", False):
        raise JobError("Scratch cleanup requires prepared root and stopped containers")
    root, device, inode, uid, gid, image = prepared
    current = job.root.lstat()
    if (
        job.root != root or stat.S_ISLNK(current.st_mode)
        or not stat.S_ISDIR(current.st_mode) or job.root.resolve() != root
        or (current.st_dev, current.st_ino, current.st_uid) != (device, inode, uid)
        or (os.getuid(), os.getgid()) != (uid, gid)
        or not image or job.get("imageDigest") != image
        or any(c in str(root) for c in ",\"\r\n")
    ):
        raise JobError("Scratch cleanup identity changed")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--read-only",
             "--entrypoint", "/bin/chown", "--mount",
             f"type=bind,src={root},dst=/grade,bind-recursive=disabled",
             image, "-Rh", f"{uid}:{gid}", "/grade"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired as error:
        raise JobError("Scratch ownership cleanup timed out") from error
    if result.returncode:
        raise JobError("Scratch ownership cleanup failed: " + result.stderr)
    shutil.rmtree(job.root)


def preserve_build_logs(job, output):
    """Keep private operator logs/summarys before check-course removes scratch."""
    if job.get("runtime") != NATIVE_RUNTIME:
        return None
    areas = [
        ("", job.root / ".native-build-private"),
        ("public-verification", job.root / "public-verification/.native-build-private"),
    ]
    present = [
        (label, path) for label, path in areas if path.exists() or path.is_symlink()
    ]
    if not present:
        return None
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    base = safe(output.parent, output.name + ".private-build-evidence")
    base.mkdir(mode=0o700, exist_ok=True)
    if not base.is_dir() or base.stat().st_mode & 0o077:
        raise JobError("Private build evidence destination is not private")
    destination = safe(
        base, job["qualifiedId"] + "/" + job["scenario"].replace(":", "-")
    )
    destination.mkdir(mode=0o700, parents=True)
    files = []
    for label, source in present:
        if source.is_symlink() or not source.is_dir():
            raise JobError("Unsafe private build evidence directory")
        target = destination / label
        if label:
            target.mkdir(mode=0o700)
        for path in source.iterdir():
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                raise JobError("Unsafe private build evidence file")
            data = path.read_bytes()
            copy = safe(target, path.name)
            copy.write_bytes(data)
            copy.chmod(0o600)
            files.append(copy.relative_to(destination).as_posix())
    manifest = destination / "files.json"
    manifest.write_text(
        json.dumps(
            {
                "qualifiedId": job["qualifiedId"],
                "scenario": job["scenario"],
                "files": files,
            },
            sort_keys=True,
        )
    )
    manifest.chmod(0o600)
    return destination


def _matches(result, expected):
    keys = {
        "student-compilation": "studentCompilation",
        "classification": "classification",
    }
    for key, field in keys.items():
        if key in expected and result.get(field) != expected[key]:
            return False, key
    if (
        "job" in expected
        and ("complete" if result.get("infrastructure") == "complete" else "failure")
        != expected["job"]
    ):
        return False, "job"
    c = result.get("counts", {})
    if expected.get("required-tests") == "all-pass" and result.get("publicResult"):
        public = result["publicResult"].get("counts", {})
        if (
            public.get("executed", 0) < 1
            or public.get("failed", 0)
            or public.get("skipped", 0)
            or public.get("aborted", 0)
        ):
            return False, "public-required-tests"
    if (
        expected.get("required-tests") == "all-pass"
        and result.get("variants")
        and result.get("classification") != "success"
    ):
        return False, "mutation-contracts"
    if (
        expected.get("required-tests") == "all-pass"
        and not result.get("variants")
        and (
            c.get("executed", 0) < 1
            or c.get("failed", 0)
            or c.get("skipped", 0)
            or c.get("aborted", 0)
        )
    ):
        return False, "required-tests"
    for name, actual in [
        ("failed-tests", c.get("failed", 0)),
        ("executed-tests", c.get("executed", 0)),
        ("score", result.get("score")),
    ]:
        if name in expected:
            if actual is None:
                return False, name
            for op, want in expected[name].items():
                if (
                    (op == "at-least" and actual < want)
                    or (op == "exactly" and actual != want)
                    or (op == "less-than" and actual >= want)
                ):
                    return False, name
    if "test-ids" in expected and not set(expected["test-ids"]).issubset(
        c.get("outcomes", {})
    ):
        return False, "test-ids"
    return True, ""


def verify_results(
    results, expectations, required_scenarios=None, unavailable=None, registry=None, expected_jobs=None
):
    if not results:
        raise JobError("No grading results")
    first = results[0]
    status = 0
    checks = []
    bindings = {}
    runtimes = {}
    observed = set()
    for r in results:
        validate("check-result", r)
        for k in (
            "scope",
            "backend",
        ):
            if r.get(k) != first.get(k):
                raise JobError("Mixed grading scopes/backends")
        rid = r["runtime"]
        image = r["imageDigest"]
        q = r["qualifiedId"]
        key = (q, r["scenario"])
        if expected_jobs is not None:
            expected = expected_jobs.get(key)
            if expected is None or any(r.get(field) != expected[field] for field in expected):
                raise JobError("Result opaque maps differ from prepared Job")
        if key in observed:
            raise JobError("Duplicate scenario result")
        observed.add(key)
        if rid in runtimes and runtimes[rid] != image:
            raise JobError("Mixed images for one runtime")
        runtimes[rid] = image
        if rid == NATIVE_RUNTIME:
            primary_build = _validate_build_observation(r)
            if "publicResult" in r:
                public_build = _validate_build_observation(r["publicResult"])
                if (primary_build["status"] == "success" and public_build["status"] == "success"
                    and public_build["artifact"]["path"] != primary_build["artifact"]["path"]):
                    raise JobError("Public build artifact differs from primary descriptor")
        binding = {
            "qualifiedId": q,
            "runtime": rid,
            "imageDigest": image,
        }
        if q in bindings and bindings[q] != binding:
            raise JobError("Mixed runtime/image for one question")
        bindings[q] = binding
        e = (
            {
                "student-compilation": "success",
                "job": "complete",
                "required-tests": "all-pass",
            }
            if r["scenario"].startswith("reference:")
            else {}
        )
        e.update(
            expectations.get(
                q + ":" + r["scenario"], expectations.get(r["scenario"], {})
            )
        )
        if not r["scenario"].startswith("contract:"):
            e["student-compilation"] = "success"
        matched, reason = _matches(r, e)
        if r["infrastructure"] != "complete":
            status = 2
            matched = False
            reason = "infrastructure"
        elif not matched or (
            r["studentCompilation"] != "success"
            and not (
                r["scenario"].startswith("contract:")
                and e.get("student-compilation") == "failure"
            )
        ):
            status = max(status, 1)
            matched = False
            reason = reason or "student-compilation"
        checks.append(
            {
                "qualifiedId": q,
                "scenario": r["scenario"],
                "matched": matched,
                "reason": reason,
            }
        )
    required = sorted(
        required_scenarios or [], key=lambda r: (r["qualifiedId"], r["scenario"])
    )
    expected = {(r["qualifiedId"], r["scenario"]): r for r in required}
    if len(expected) != len(required):
        raise JobError("Duplicate required scenario")
    unavailable = sorted(
        unavailable or [], key=lambda r: (r["qualifiedId"], r["scenario"])
    )
    absent = set()
    for entry in unavailable:
        key = (entry["qualifiedId"], entry["scenario"])
        if (
            key in absent
            or key in observed
            or key not in expected
            or not expected[key]["optional"]
            or not entry["scenario"].startswith("reference:")
        ):
            raise JobError("Invalid unavailable optional-reference observation")
        absent.add(key)
    if required and observed - set(expected):
        raise JobError("Undeclared scenario result")
    complete = bool(required) and observed | absent == set(expected)
    summary = {
        "schemaVersion": 1,
        "toolVersion": TOOL_VERSION,
        "backend": first["backend"],
        "scope": first["scope"],
        "status": ["success", "defect", "infrastructure-failure"][status],
        "exitCode": status,
        "coverage": "complete" if complete else "partial",
        "scenarios": required,
        "unavailableReferences": unavailable,
        "checkedIds": sorted(bindings),
        "questionBindings": [bindings[q] for q in sorted(bindings)],
        "runtimes": runtimes,
        "expectations": checks,
    }
    native_builds = [
        {
            "qualifiedId": r["qualifiedId"],
            "scenario": r["scenario"],
            **r["buildEvidence"],
            "outcome": {
                key: r[key]
                for key in (
                    "classification",
                    "infrastructure",
                    "studentCompilation",
                    "trustedCompilation",
                    "apiPrecheck",
                    "dependentExecution",
                )
                if key in r
            },
        }
        for r in results
        if r["runtime"] == NATIVE_RUNTIME
    ]
    if native_builds:
        summary["buildEvidence"] = sorted(
            native_builds, key=lambda r: (r["qualifiedId"], r["scenario"])
        )
    return summary
