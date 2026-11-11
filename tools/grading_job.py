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
from collections.abc import Collection, Mapping, Sequence
from typing import Literal, Protocol, TypeGuard, TypedDict, runtime_checkable
from json_boundary import JSONValue, is_object, is_list, json_object, json_value
from grading_types import (ApiPrecheck, AdditionalSourcePolicy, BuildEvidence, BuildReceipt, BuildStageFacts, CheckResult, ContractCases, Discovery, Expectations, ExpectationResult, GradingJobPayload, JavaConfig, JavaBuild, JSONInteger, JobBindings, NativeChecks, NativeProject, Outcome, QuestionBinding, ResultCounts, RunLimits, Scenario, SelectedFile, UnavailableReference, VerificationReceipt)

ROOT = Path(__file__).resolve().parents[1]
TOOL_VERSION = "2.1.0"


class JobError(Exception):
    pass


class ProjectDefect(JobError):
    pass


class GradingJob(dict[str, object]):
    """Переносимые поля проверяются отдельно от приватного scratch."""

    root: Path
    _scratch: tuple[Path, int, int, int, int, str | None]
    _containers_stopped: bool
    containerName: str

    def initialize_scratch(self, root: Path, image: str | None) -> None:
        """Связать приватный scratch с его фактической файловой идентичностью."""
        self.root = root
        scratch = root.lstat()
        self._scratch = (root, scratch.st_dev, scratch.st_ino, os.getuid(), os.getgid(), image)
        self._containers_stopped = True

    def mark_containers_stopped(self, stopped: bool) -> None:
        """Состояние потомков не является частью переносимого payload."""
        self._containers_stopped = stopped

    def checked_payload(self) -> GradingJobPayload:
        value: object = self
        if not _job_payload(value):
            raise JobError("Invalid prepared job payload")
        return value


def safe(root: str | Path, name: object) -> Path:
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


@runtime_checkable
class _OutcomeValidator(Protocol):
    def __call__(self, value: object, *, student_tests: bool = False) -> None: ...


@runtime_checkable
class _UniqueObject(Protocol):
    def __call__(self, pairs: Sequence[tuple[str, object]]) -> dict[str, object]: ...


class _JUnitHelpers(TypedDict):
    validate_outcome: _OutcomeValidator
    unique_json_object: _UniqueObject


@functools.cache
def _junit_result_helpers() -> _JUnitHelpers:
    import runpy

    helpers: dict[str, object] = runpy.run_path(str(ROOT / "runtime/junit_result.py"))
    validator, unique = helpers.get("validate_outcome"), helpers.get("unique_json_object")
    if not isinstance(validator, _OutcomeValidator) or not isinstance(unique, _UniqueObject):
        raise JobError("Канонический JUnit decoder недоступен")
    return {"validate_outcome": validator, "unique_json_object": unique}


@runtime_checkable
class _SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


def _schema_validator(value: object) -> _SchemaValidator:
    if not isinstance(value, _SchemaValidator):
        raise JobError("Канонический JSON Schema validator недоступен")
    return value


def validate(name: str, value: object) -> None:
    if name == "grading-job":
        name = "grading-job-v3"
    try:
        schema = json_object(json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text()))
        validator = _schema_validator(jsonschema.Draft202012Validator(schema))
        validator.validate(json_value(value))
        if name == "check-result" and is_object(value) and value.get("runtime") in (
            "java25-junit-v1",
            "java25-gradle-junit-v1",
            "java25-mutation-v1",
        ):
            _junit_result_helpers()["validate_outcome"](
                value, student_tests=value["runtime"] == "java25-mutation-v1"
            )
    except (jsonschema.ValidationError, OSError, ValueError) as error:
        raise JobError(f"Invalid {name}: {error}") from error


def validate_profile(check: object) -> None:
    validate("project-check", check)


def _native_checks(value: object) -> TypeGuard[NativeChecks]:
    # Уточнение формы разрешено только после полной проверки этой схемой.
    validate("native-checks", value)
    return True


def _contract_cases(value: object) -> TypeGuard[ContractCases]:
    validate("contract-cases", value)
    return True


def _job_payload(value: object) -> TypeGuard[GradingJobPayload]:
    validate("grading-job", value)
    return True


def _check_result(value: object) -> TypeGuard[CheckResult]:
    validate("check-result", value)
    return True


def _runtime_profile(registry: object, runtime: str) -> dict[str, object]:
    if not is_object(registry) or not is_object(registry.get("profiles")):
        raise JobError("Invalid runtime profile registry")
    profiles = registry["profiles"]
    if not is_object(profiles):
        raise JobError("Invalid runtime profile registry")
    profile = profiles.get(runtime)
    if not is_object(profile) or any(not isinstance(key, str) for key in profile):
        raise JobError("Invalid runtime profile")
    return {key: item for key, item in profile.items() if isinstance(key, str)}


def _selected_file(value: object) -> TypeGuard[SelectedFile]:
    return (is_object(value) and set(value) == {"name", "target", "data"}
            and all(isinstance(item, str) for item in value.values()))


def inventory(manifest: object) -> list[NativeProject]:
    if not _native_checks(manifest):
        raise JobError("Invalid native checks")
    selected: dict[str, NativeProject] = {}
    for project in manifest["projects"]:
        q = project["qualifiedId"]
        if q in selected:
            raise JobError("Duplicate selected check " + q)
        if project.get("check"):
            selected[q] = project
    return [selected[q] for q in sorted(selected)]


def load_runtime_registry() -> dict[str, JSONValue]:
    return json_object(json.loads((ROOT / "runtime-profiles.json").read_text()))


def selected_bytes(item: SelectedFile) -> bytes:
    try:
        data = base64.b64decode(item["data"], validate=True)
    except (ValueError, binascii.Error, KeyError, TypeError) as error:
        raise JobError("Invalid selected file bytes") from error
    if len(data) > 1048576:
        raise JobError("Selected file size limit")
    return data


def _selection(items: object) -> list[SelectedFile]:
    if not is_list(items) or len(items) > 4096:
        raise JobError("Selected file count limit")
    names: set[str] = set(); targets: set[str] = set(); total = 0
    selected: list[SelectedFile] = []
    for item in items:
        if not _selected_file(item):
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
        selected.append(item.copy())
    return selected


def _fixture_selection(items: object) -> list[SelectedFile]:
    if not is_list(items) or len(items)>4096:
        raise JobError("Selected fixture count limit")
    selected: dict[tuple[str, str], SelectedFile]={};total=0
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


def _cases(project: NativeProject) -> ContractCases:
    record = project.get("contractCases")
    if not record:
        raise JobError("Missing selected contract cases")
    _selection([record])
    try: cases: object = json.loads(selected_bytes(record))
    except (ValueError, UnicodeError) as error: raise JobError("Invalid contract cases JSON") from error
    if not _contract_cases(cases):
        raise JobError("Invalid contract cases")
    if len({c["id"] for c in cases["cases"]}) != len(cases["cases"]):
        raise JobError("Duplicate contract case ID")
    return cases


def scenario_inventory(manifest: object, snapshot: Path | None = None, ids: Collection[str] | None = None) -> list[Scenario]:
    records: list[Scenario] = []
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
    manifest: object, snapshot: str | Path | None, id: str, scenario: str,
    scope: str = "declared", delivery: object = None, registry: object = None,
) -> GradingJob:
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
    reference_source_names: list[str] | None = None
    expected_case: Expectations | None = None
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
        replacements: dict[str, SelectedFile] = {}
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
            replacements[x["submission"]] = bound[0].copy()
        selected = (
            list(replacements.values())
            if optional_primary
            else [replacements.get(x["name"], x) for x in sources]
        )
        if not optional_primary and archive_name is not None and archive_name in replacements:
            selected.append(replacements[archive_name])
        expected_case = case[0]["expected"]
    elif scenario != "starter":
        raise JobError("Unknown scenario")
    java: JavaConfig = {
        "release": 25,
        "encoding": "UTF-8",
        "compiler-options": ["-proc:none", "-Xmaxerrs", "5"],
    }
    java.update(check.get("java", {}))
    limits: RunLimits = {
        "outer-seconds": 30,
        "compile-seconds": 15,
        "run-seconds": 10,
        "networking": False,
        "max-output-bytes": 65536,
    }
    limits.update(check.get("limits", {}))
    discovery: Discovery = {"min-executed": 1, "allow-skipped": False}
    discovery.update(check.get("discovery", {}))
    grading: dict[str, object] = {
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
        "discovery": discovery,
    }

    def api_selection(field: Literal["apiPrecheck", "verificationApiPrecheck"], selection: Sequence[SelectedFile]) -> ApiPrecheck | None:
        value = p.get(field)
        if value is None:
            return None
        names = {x["name"] for x in selection}
        declaration = check.get(
            "api-precheck" if field == "apiPrecheck" else "verification-api-precheck",
            {},
        )
        if (
            set(value) != {"files", "entry"}
            or not value["files"]
            or len(set(value["files"])) != len(value["files"])
            or not set(value["files"]) < names
            or value["entry"] != declaration.get("entry")
        ):
            raise JobError(
                "API precheck is not a proper subset of selected trusted sources"
            )
        return {"entry": value["entry"], "files": list(value["files"])}

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
        translated: AdditionalSourcePolicy = {
            "archive": extra_policy["archive"], "maxFiles": extra_policy["max-files"],
            "maxFileBytes": extra_policy["max-file-bytes"], "maxTotalBytes": extra_policy["max-total-bytes"],
            "maxArchiveBytes": extra_policy["max-archive-bytes"],
        }
        if "primary-required" in extra_policy:
            translated["primaryRequired"] = extra_policy["primary-required"]
        if "allow-additional" in extra_policy:
            translated["allowAdditional"] = extra_policy["allow-additional"]
        grading["additionalJavaSources"] = translated
    if "java-build" in check:
        build = check["java-build"]
        translated_build: JavaBuild = {"kind": build["kind"], "artifact": build["artifact"]}
        if "main-class" in build:
            translated_build["mainClass"] = build["main-class"]
        grading["javaBuild"] = translated_build
    if "variants" in check:
        grading["variants"] = check["variants"]
    runtime = _runtime_profile(registry or load_runtime_registry(), check["runtime"])
    if check["runtime"] == "fish-git-v1":
        grading.pop("java")
    expectations = (
        expected_case
        if expected_case is not None
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
        if not is_object(delivery) or id not in code_ids({k:v for k,v in delivery.items() if k != "_root"}):
            raise JobError("ID absent from automatic delivery")
        delivery_root = delivery.get("_root", "")
        if not isinstance(delivery_root, str):
            raise JobError("Invalid delivery root")
        native = Path(delivery_root)
        question = "questions/" + id + "/"
        info = json_object(json.loads(file_bytes(native, question + "info.json")))
        external = info.get("externalGradingOptions", {})
        if not isinstance(external, dict) or external.get("image") != job["imageDigest"]:
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
    payload: object = job
    if not _job_payload(payload):
        raise JobError("Invalid prepared job payload")
    job.initialize_scratch(Path(tempfile.mkdtemp(prefix="grading-job-")), payload["imageDigest"])
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
    if generated_archive is not None and archive_name is not None:
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




def _build_evidence(value: object) -> TypeGuard[BuildEvidence]:
    if not is_object(value) or type(value.get("schemaVersion")) is not int or any(
        not isinstance(value.get(key), str) for key in ("kind", "status")
    ):
        return False
    if "reason" in value and not isinstance(value["reason"], str):
        return False
    if "durationSeconds" in value and (
        isinstance(value["durationSeconds"], bool) or not isinstance(value["durationSeconds"], (int, float))
    ):
        return False
    if "artifact" in value:
        artifact = value["artifact"]
        if not is_object(artifact) or not isinstance(artifact.get("path"), str) or type(artifact.get("bytes")) is not int:
            return False
    return True


def _validate_build_observation(result: object, artifact: str | None = None) -> BuildEvidence:
    if not is_object(result):
        raise JobError("Native build outcome is missing")
    proof = result.get("buildEvidence")
    if not _build_evidence(proof):
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
        produced = proof.get("artifact")
        if artifact is not None and (produced is None or produced["path"] != "build/libs/" + artifact):
            raise JobError("Build artifact differs from descriptor")
    return proof


@runtime_checkable
class _HostGrader(Protocol):
    def grade(self, job_dir: Path) -> object: ...


@runtime_checkable
class _RegistryHostGrader(Protocol):
    def grade(self, job_dir: Path, registry: object = None) -> object: ...


def _remove_container(name: str) -> None:
    """Подтвердить удаление только собственного заранее выбранного контейнера."""
    cleanup = subprocess.run(
        ["docker", "rm", "--force", name],
        capture_output=True, text=True, timeout=10,
    )
    if cleanup.returncode and "No such container" not in cleanup.stderr:
        raise JobError(cleanup.stderr)


def _container_diagnostics(stdout: str | bytes | None, stderr: str | bytes | None,
                           code: int | None, termination: str, maximum: JSONInteger) -> dict[str, str]:
    observation = {"stage": "container", "container.termination": termination}
    if code is not None:
        observation["container.exitCode"] = str(code)
    remaining = int(maximum)
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        raw = value if isinstance(value, bytes) else (value or "").encode("utf-8")
        text = raw.decode("utf-8", errors="replace").encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        observation["container." + name] = text
        remaining -= len(text.encode("utf-8"))
    return observation


def run_job(job: GradingJob, backend: str = "host", registry: object = None) -> CheckResult:
    if getattr(job, "_containers_stopped", True) is False:
        raise JobError("Grading retry requires stopped containers")
    raw_payload: object = job
    if not _job_payload(raw_payload):
        raise JobError("Invalid prepared job payload")
    payload = raw_payload
    if not getattr(job, "root", None):
        raise JobError("Prepared private job root required")
    common: JobBindings = {
        "scope": payload["scope"], "qualifiedId": payload["qualifiedId"],
        "scenario": payload["scenario"], "runtime": payload["runtime"], "imageDigest": payload["imageDigest"],
    }
    native = payload["runtime"] == NATIVE_RUNTIME
    result: dict[str, JSONValue]
    process_diagnostics: dict[str, str] = {}
    try:
        if backend == "host":
            profile = _runtime_profile(registry or load_runtime_registry(), payload["runtime"])
            spec = importlib.util.spec_from_file_location(
                "platform_grader",
                safe(ROOT, profile.get("runner", "images/java25-grader/grade.py")),
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("Загрузчик локального Python-модуля недоступен")
            grader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(grader)
            error_class: object = getattr(grader, "GraderError", None)
            caught_errors: tuple[type[Exception], ...] = ()
            if isinstance(error_class, type) and issubclass(error_class, Exception):
                caught_errors = (error_class,)
            try:
                if registry is not None and payload["runtime"] != "fish-git-v1":
                    if not isinstance(grader, _RegistryHostGrader):
                        raise JobError("Runtime registry consumer is unavailable")
                    result = json_object(grader.grade(job.root, registry=registry))
                else:
                    if not isinstance(grader, _HostGrader):
                        raise JobError("Runtime grader contract is unavailable")
                    result = json_object(grader.grade(job.root))
            except caught_errors as error:
                observation: object = getattr(error, "outcome", None)
                if observation is None:
                    raise JobError(str(error)) from error
                result = json_object(observation)
        elif backend == "container":
            if not payload["imageDigest"]:
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
                payload["imageDigest"],
                "--verification",
            ]
            job.mark_containers_stopped(False)
            try:
                p = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=payload["grading"]["limits"]["outer-seconds"],
                )
            except OSError as error:
                process_diagnostics = _container_diagnostics(None, str(error), None, "spawn-error", payload["grading"]["limits"]["max-output-bytes"])
                raise
            except (KeyboardInterrupt, subprocess.TimeoutExpired) as error:
                if isinstance(error, subprocess.TimeoutExpired):
                    process_diagnostics = _container_diagnostics(error.stdout, error.stderr, None, "timeout", payload["grading"]["limits"]["max-output-bytes"])
                message = "Outer Docker timeout" if isinstance(error, subprocess.TimeoutExpired) else "Docker run interrupted"
                try:
                    _remove_container(job.containerName)
                except (JobError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as cleanup_error:
                    if isinstance(error, KeyboardInterrupt):
                        raise error from cleanup_error
                    if isinstance(cleanup_error, KeyboardInterrupt):
                        raise
                    raise JobError(
                        message + "; container cleanup failed: " + str(cleanup_error)
                    ) from cleanup_error
                job.mark_containers_stopped(True)
                if isinstance(error, KeyboardInterrupt):
                    raise
                raise JobError(message + "; container removed") from error
            process_diagnostics = _container_diagnostics(p.stdout, p.stderr, p.returncode, "signal" if p.returncode < 0 else "exit", payload["grading"]["limits"]["max-output-bytes"])
            if p.returncode not in (0, 2):
                raise JobError("Docker infrastructure failure (exit " + str(p.returncode) + "): " + process_diagnostics["container.stderr"])
            job.mark_containers_stopped(True)
            result = json_object(json.loads(
                (job.root / "results/results.json").read_text(),
                object_pairs_hook=_junit_result_helpers()["unique_json_object"],
            ))
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
        if process_diagnostics:
            result["diagnostics"] = json_value(process_diagnostics)
    if native:
        if "buildEvidence" not in result and result.get("infrastructure") == "failure":
            result["buildEvidence"] = {
                "schemaVersion": 1,
                "kind": "gradle-jar-v1",
                "status": "failure",
                "reason": "configuration",
            }
        build = payload["grading"].get("javaBuild")
        if build is None:
            raise JobError("Native Java build policy required")
        _validate_build_observation(result, build["artifact"])
    if (job.root / "public-verification").is_dir() and result.get(
        "infrastructure"
    ) == "complete":
        publicjob = GradingJob(job)
        publicjob.root = job.root / "public-verification"
        publicjob.mark_containers_stopped(True)
        primary_stopped = getattr(job, "_containers_stopped", True)
        job.mark_containers_stopped(False)
        try:
            publicresult = run_job(publicjob, backend, registry)
        finally:
            job.mark_containers_stopped(primary_stopped and getattr(publicjob, "_containers_stopped", False))
        result["publicResult"] = {
            k: v
            for k, v in json_object(publicresult).items()
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
    value: object = {"schemaVersion": 1, "backend": backend, **common, **result}
    if not _check_result(value):
        raise JobError("Invalid runtime result")
    return value


def _tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)


def _scratch_record(value: object) -> TypeGuard[tuple[Path, int, int, int, int, str | None]]:
    return (_tuple(value) and len(value) == 6 and isinstance(value[0], Path)
            and all(type(item) is int for item in value[1:5])
            and (value[5] is None or isinstance(value[5], str)))


def cleanup_job(job: object, backend: str) -> None:
    """Удалить scratch; вернуть владельца только после остановки всех контейнеров."""
    prepared: object = getattr(job, "_scratch", None)
    if not _scratch_record(prepared) or not getattr(job, "_containers_stopped", False):
        raise JobError("Scratch cleanup requires prepared root and stopped containers")
    root, device, inode, uid, gid, image = prepared
    def check_root() -> None:
        job_root: object = getattr(job, "root", None)
        if not isinstance(job_root, Path):
            raise JobError("Scratch cleanup identity changed")
        current = job_root.lstat()
        if (
            job_root != root or stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode) or job_root.resolve() != root
            or (current.st_dev, current.st_ino, current.st_uid) != (device, inode, uid)
            or (os.getuid(), os.getgid()) != (uid, gid)
        ):
            raise JobError("Scratch cleanup identity changed")
    check_root()
    try:
        shutil.rmtree(root)
        return
    except PermissionError:
        if backend != "container":
            raise
    check_root()
    if (
        not image or not is_object(job) or job.get("imageDigest") != image
        or any(c in str(root) for c in ",\"\r\n")
    ):
        raise JobError("Scratch cleanup identity changed")
    cleanup_name = "plcleanup-" + secrets.token_hex(12)
    setattr(job, "_containers_stopped", False)
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--name", cleanup_name, "--network", "none", "--read-only",
             "--entrypoint", "/bin/chown", "--mount",
             f"type=bind,src={root},dst=/grade,bind-recursive=disabled",
             image, "-Rh", f"{uid}:{gid}", "/grade"],
            capture_output=True, text=True, timeout=10,
        )
    except (KeyboardInterrupt, subprocess.TimeoutExpired) as error:
        message = "Scratch ownership cleanup timed out" if isinstance(error, subprocess.TimeoutExpired) else "Scratch ownership cleanup interrupted"
        try:
            _remove_container(cleanup_name)
        except (JobError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as cleanup_error:
            if isinstance(error, KeyboardInterrupt):
                raise error from cleanup_error
            if isinstance(cleanup_error, KeyboardInterrupt):
                raise
            raise JobError(
                message + "; container cleanup failed: " + str(cleanup_error)
            ) from cleanup_error
        setattr(job, "_containers_stopped", True)
        if isinstance(error, KeyboardInterrupt):
            raise
        raise JobError(message + "; container removed") from error
    if result.returncode:
        raise JobError("Scratch ownership cleanup failed: " + result.stderr)
    setattr(job, "_containers_stopped", True)
    check_root()
    shutil.rmtree(root)


def preserve_build_logs(job: object, output: str | Path) -> Path | None:
    """Keep private operator logs/summarys before check-course removes scratch."""
    if not is_object(job) or job.get("runtime") != NATIVE_RUNTIME:
        return None
    job_root: object = getattr(job, "root", None)
    qualified_id, scenario = job.get("qualifiedId"), job.get("scenario")
    if not isinstance(job_root, Path) or not isinstance(qualified_id, str) or not isinstance(scenario, str):
        raise JobError("Prepared native build job identity required")
    areas = [
        ("", job_root / ".native-build-private"),
        ("public-verification", job_root / "public-verification/.native-build-private"),
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
        base, qualified_id + "/" + scenario.replace(":", "-")
    )
    destination.mkdir(mode=0o700, parents=True)
    files: list[str] = []
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


def _count(counts: ResultCounts | None, key: Literal["executed", "failed", "skipped", "aborted"]) -> JSONInteger:
    return counts[key] if counts is not None else 0


def _range_matches(actual: float | None, minimum: float | None, exactly: float | None, below: float | None = None) -> bool:
    return (actual is not None and (minimum is None or actual >= minimum)
            and (exactly is None or actual == exactly) and (below is None or actual < below))


def _matches(result: Outcome[ResultCounts], expected: Expectations) -> tuple[bool, str]:
    if "student-compilation" in expected and result.get("studentCompilation") != expected["student-compilation"]:
        return False, "student-compilation"
    if "classification" in expected and result["classification"] != expected["classification"]:
        return False, "classification"
    if "job" in expected and ("complete" if result["infrastructure"] == "complete" else "failure") != expected["job"]:
        return False, "job"
    counts = result.get("counts")
    public = result.get("publicResult")
    if expected.get("required-tests") == "all-pass" and public:
        public_counts = public.get("counts")
        if (_count(public_counts, "executed") < 1 or _count(public_counts, "failed")
            or _count(public_counts, "skipped") or _count(public_counts, "aborted")):
            return False, "public-required-tests"
    if expected.get("required-tests") == "all-pass" and result.get("variants") and result["classification"] != "success":
        return False, "mutation-contracts"
    if expected.get("required-tests") == "all-pass" and not result.get("variants") and (
        _count(counts, "executed") < 1 or _count(counts, "failed")
        or _count(counts, "skipped") or _count(counts, "aborted")
    ):
        return False, "required-tests"
    for name in ("failed-tests", "executed-tests"):
        bound = expected.get("failed-tests") if name == "failed-tests" else expected.get("executed-tests")
        actual = _count(counts, "failed" if name == "failed-tests" else "executed")
        if bound is not None and not _range_matches(actual, bound.get("at-least"), bound.get("exactly")):
            return False, name
    score = expected.get("score")
    if score is not None and not _range_matches(result.get("score"), score.get("at-least"), score.get("exactly"), score.get("less-than")):
        return False, "score"
    outcomes: dict[str, str] = counts["outcomes"] if counts is not None else {}
    if "test-ids" in expected and not set(expected["test-ids"]).issubset(outcomes):
        return False, "test-ids"
    return True, ""


def _student_compilation(result: CheckResult) -> str:
    if "studentCompilation" not in result:
        raise KeyError("studentCompilation")
    return result["studentCompilation"]


def verify_results(
    results: Sequence[object], expectations: Mapping[str, Expectations],
    required_scenarios: Sequence[Scenario] | None = None,
    unavailable: Sequence[UnavailableReference] | None = None,
    registry: object = None,
    expected_jobs: Mapping[tuple[str, str], Mapping[str, object]] | None = None,
) -> VerificationReceipt:
    if not results:
        raise JobError("No grading results")
    checked: list[CheckResult] = []
    for value in results:
        if not _check_result(value):
            raise JobError("Invalid grading result")
        checked.append(value)
    first = checked[0]
    status = 0
    checks: list[ExpectationResult] = []
    bindings: dict[str, QuestionBinding] = {}
    runtimes: dict[str, str | None] = {}
    observed: set[tuple[str, str]] = set()
    for r in checked:
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
                primary_artifact, public_artifact = primary_build.get("artifact"), public_build.get("artifact")
                if (primary_build["status"] == "success" and public_build["status"] == "success"
                    and primary_artifact is not None and public_artifact is not None
                    and public_artifact["path"] != primary_artifact["path"]):
                    raise JobError("Public build artifact differs from primary descriptor")
        binding: QuestionBinding = {
            "qualifiedId": q,
            "runtime": rid,
            "imageDigest": image,
        }
        if q in bindings and bindings[q] != binding:
            raise JobError("Mixed runtime/image for one question")
        bindings[q] = binding
        e: Expectations = (
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
            _student_compilation(r) != "success"
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
    absent: set[tuple[str,str]] = set()
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
    summary: VerificationReceipt = {
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
    native_builds: list[BuildReceipt] = []
    for result in checked:
        if result["runtime"] != NATIVE_RUNTIME:
            continue
        proof = _validate_build_observation(result)
        stages: BuildStageFacts = {"classification": result["classification"], "infrastructure": result["infrastructure"]}
        if "studentCompilation" in result:
            stages["studentCompilation"] = result["studentCompilation"]
        if "trustedCompilation" in result:
            stages["trustedCompilation"] = result["trustedCompilation"]
        if "apiPrecheck" in result:
            stages["apiPrecheck"] = result["apiPrecheck"]
        if "dependentExecution" in result:
            stages["dependentExecution"] = result["dependentExecution"]
        native_builds.append({**proof, "qualifiedId": result["qualifiedId"], "scenario": result["scenario"], "outcome": stages})
    if native_builds:
        summary["buildEvidence"] = sorted(
            native_builds, key=lambda r: (r["qualifiedId"], r["scenario"])
        )
    return summary
