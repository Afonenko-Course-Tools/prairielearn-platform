"""Explicit source inventory -> private /grade jobs -> matching receipts."""

import hashlib
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


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def safe(root, name):
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or Path(name).is_absolute()
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
    try:
        from referencing import Registry, Resource

        automatic = json.loads(
            (ROOT / "schemas/verification-receipt.schema.json").read_text()
        )
        registry = Registry().with_resource(
            automatic["$id"], Resource.from_contents(automatic)
        )
        jsonschema.Draft202012Validator(
            json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text()),
            registry=registry,
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
    if manifest.get("schemaVersion") != 1 or not isinstance(
        manifest.get("projects"), list
    ):
        raise JobError("Expected checks manifest version1")
    selected = {}
    for p in manifest["projects"]:
        if not p.get("check"):
            continue
        q = p.get("qualifiedId")
        if not isinstance(q, str) or "/" not in q:
            raise JobError("Missing qualified ID")
        if q in selected and selected[q] != p:
            raise JobError("Conflicting duplicate check " + q)
        selected[q] = p
    return [selected[q] for q in sorted(selected)]


def load_runtime_registry():
    return json.loads((ROOT / "runtime-profiles.json").read_text())


def runtime_evidence(runtime, registry=None):
    registry = registry or load_runtime_registry()
    if runtime not in registry["profiles"]:
        raise JobError("Unknown runtime " + runtime)
    profile = registry["profiles"][runtime]
    bundle = safe(ROOT, profile["bundle"])
    actual = {
        p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()
    }
    if actual != set(profile["files"]):
        raise JobError("Runtime dependency closure changed")
    for name, sha in profile["files"].items():
        if hashlib.sha256(safe(bundle, name).read_bytes()).hexdigest() != sha:
            raise JobError("Runtime dependency checksum changed")
    runner = hashlib.sha256(
        safe(ROOT, profile.get("runner", "images/java25-grader/grade.py")).read_bytes()
    ).hexdigest()
    if runner != profile["runnerSha256"]:
        raise JobError("Runtime runner checksum changed")
    for name, sha in profile["sharedFiles"].items():
        if hashlib.sha256(safe(ROOT, name).read_bytes()).hexdigest() != sha:
            raise JobError("Shared runtime checksum changed")
    files = {**profile["files"], **profile["sharedFiles"], "runner/grade.py": runner}
    return {"dependencyHashes": files, "dependencyHash": digest(files)}


def scenario_inventory(manifest, snapshot, ids=None):
    snapshot = Path(os.path.abspath(snapshot))
    if snapshot.resolve() != snapshot or not snapshot.is_dir():
        raise JobError("Scenario snapshot root must be a real directory")
    records = []
    for p in inventory(manifest):
        if ids is not None and p["qualifiedId"] not in ids:
            continue
        q = p["qualifiedId"]
        check = p["check"]
        records.append({"qualifiedId": q, "scenario": "starter", "optional": False})
        for ref in check.get("references", []):
            records.append(
                {
                    "qualifiedId": q,
                    "scenario": "reference:" + ref["name"],
                    "optional": ref.get("optional", False),
                }
            )
        if check.get("contract-cases"):
            project = safe(safe(Path(snapshot), manifest["bookRoot"]), p["projectRoot"])
            file = safe(project, check["contract-cases"])
            expected = p.get("contractCasesHash")
            if (
                not expected
                or expected["projectRelativePath"] != check["contract-cases"]
                or hashlib.sha256(file.read_bytes()).hexdigest() != expected["sha256"]
            ):
                raise JobError("Contract cases inventory checksum missing or changed")
            cases = json.loads(file.read_text())
            validate("contract-cases", cases)
            for case in cases["cases"]:
                records.append(
                    {
                        "qualifiedId": q,
                        "scenario": "contract:" + case["id"],
                        "optional": False,
                    }
                )
    records.sort(key=lambda r: (r["qualifiedId"], r["scenario"]))
    keys = [(r["qualifiedId"], r["scenario"]) for r in records]
    if len(keys) != len(set(keys)):
        raise JobError("Duplicate scenario inventory entry")
    return records


def _selection(project, items):
    out = []
    names = set()
    for x in items:
        path = safe(project, x["projectRelativePath"])
        target = x["submissionRelativePath"]
        safe(project, target)
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != x["sha256"]
        ):
            raise JobError("Source snapshot changed: " + x["projectRelativePath"])
        if target in names:
            raise JobError("Duplicate output source " + target)
        names.add(target)
        out.append(dict(x))
    return out


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
    snapshot = Path(os.path.abspath(snapshot))
    if snapshot.resolve() != snapshot:
        raise JobError("Snapshot root must be an absolute real directory")
    book = safe(Path(snapshot), manifest["bookRoot"])
    project = safe(book, p["projectRoot"])
    sources = _selection(project, p.get("sources", []))
    tests = _selection(project, p.get("trustedTests", []))
    public = _selection(project, p.get("verificationTests", []))
    if p.get("readiness", {}).get("ready") is False or not sources or not tests:
        raise ProjectDefect("Selected project is incomplete: " + id)
    if p.get("contractCasesHash"):
        x = p["contractCasesHash"]
        f = safe(project, x["projectRelativePath"])
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != x["sha256"]:
            raise JobError("Contract cases snapshot changed")
    for x in p.get("contractFixtures", []):
        f = safe(project, x["projectRelativePath"])
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != x["sha256"]:
            raise JobError(
                "Contract fixture snapshot changed: " + x["projectRelativePath"]
            )
    selected = sources
    extra_policy = check.get("additional-java-sources")
    archive_name = extra_policy["archive"] if extra_policy else None
    optional_primary = (
        extra_policy is not None and extra_policy.get("primary-required", True) is False
    )
    primary_names = {x["submissionRelativePath"] for x in sources}
    generated_archive = None
    if archive_name:
        reserved = [
            *primary_names,
            *[x["submissionRelativePath"] for x in [*tests, *public]],
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
        root = safe(project, refs[0]["root"])
        if not root.is_dir():
            raise JobError(
                "reference-unavailable:" + name
                if refs[0].get("optional", False)
                else "Missing required reference " + name
            )
        declared = [r for r in p.get("references", []) if r["name"] == name]
        if len(declared) != 1:
            raise JobError("Named reference inventory missing " + name)
        selected = _selection(project, declared[0].get("sources", []))
        reference_names = {x["submissionRelativePath"] for x in selected}
        if (not extra_policy and reference_names != primary_names) or (
            not optional_primary and not primary_names <= reference_names
        ):
            raise JobError("Reference source mapping differs from student source names")
        extras = [
            x for x in selected if x["submissionRelativePath"] not in primary_names
        ]
        if extras:
            if any(not x["submissionRelativePath"].endswith(".java") for x in extras):
                raise JobError("Reference extras must be Java sources")
            buffer = io.BytesIO()
            with zipfile.ZipFile(
                buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
            ) as archive:
                for x in sorted(extras, key=lambda x: x["submissionRelativePath"]):
                    info = zipfile.ZipInfo(
                        x["submissionRelativePath"], date_time=(1980, 1, 1, 0, 0, 0)
                    )
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(
                        info, safe(project, x["projectRelativePath"]).read_bytes()
                    )
            generated_archive = buffer.getvalue()
        for x in selected:
            f = safe(root, x["submissionRelativePath"])
            if not f.is_file():
                raise JobError(
                    "Reference source mapping missing " + x["submissionRelativePath"]
                )
            if not any(
                y["projectRelativePath"] == f.relative_to(project).as_posix()
                for y in selected
            ):
                raise JobError("Reference selection does not match declared root")
    elif scenario.startswith("contract:"):
        path = check.get("contract-cases")
        if not path:
            raise JobError("No declared contract cases")
        cases = json.loads(safe(project, path).read_text())
        validate("contract-cases", cases)
        if len({c["id"] for c in cases["cases"]}) != len(cases["cases"]):
            raise JobError("Duplicate contract case ID")
        case = [c for c in cases["cases"] if c["id"] == scenario.split(":", 1)[1]]
        if len(case) != 1:
            raise JobError("Unknown contract case")
        replacements = {}
        for x in case[0]["sources"]:
            if not x["fixture"].startswith("tests/fixtures/") or x[
                "submission"
            ] not in primary_names | ({archive_name} if archive_name else set()):
                raise JobError("Unauthorized contract fixture/submission")
            f = safe(project, x["fixture"])
            if not f.is_file():
                raise JobError("Missing contract fixture")
            if x["submission"] in replacements:
                raise JobError("Duplicate fixture submission")
            replacements[x["submission"]] = {
                "projectRelativePath": x["fixture"],
                "submissionRelativePath": x["submission"],
                "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
            }
        selected = (
            list(replacements.values())
            if optional_primary
            else [replacements.get(x["submissionRelativePath"], x) for x in sources]
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
        "sourceFiles": [x["submissionRelativePath"] for x in sources],
        "testFiles": [x["submissionRelativePath"] for x in tests],
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
        names = {x["submissionRelativePath"] for x in selection}
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
    if "feedback" in check:
        grading["feedback"] = {
            "requirement": check["feedback"]["requirement"],
            "whatCheck": check["feedback"]["what-check"],
        }
    if "public-cases" in check:
        grading["publicCases"] = check["public-cases"]
    if api:
        grading["apiPrecheck"] = api
    if extra_policy:
        grading["additionalJavaSources"] = {
            **(
                {"primaryRequired": extra_policy["primary-required"]}
                if "primary-required" in extra_policy
                else {}
            ),
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
            "mainClass": build["main-class"],
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
        schemaVersion=1,
        scope=scope,
        qualifiedId=id,
        scenario=scenario,
        sourceSnapshotHash=manifest["sourceSnapshotHash"],
        inventoryHash=manifest["inventoryHash"],
        runtime=check["runtime"],
        imageDigest=runtime["image"] or os.environ.get("PL_LOCAL_IMAGE_ID"),
        sources=selected,
        trustedTests=tests,
        verificationTests=public,
        grading=grading,
        expectations=expectations,
        sourceHashes={x["projectRelativePath"]: x["sha256"] for x in selected},
        testsHashes={x["projectRelativePath"]: x["sha256"] for x in [*tests, *public]},
    )
    if generated_archive is not None:
        job["sourceHashes"]["$generated/" + archive_name] = hashlib.sha256(
            generated_archive
        ).hexdigest()
    if scope == "delivery":
        if (
            not delivery
            or delivery.get("schemaVersion") != 3
            or id not in delivery.get("questions", [])
        ):
            raise JobError("ID absent from delivery")
        job["deliveryHash"] = delivery["deliveryHash"]
        expected_scenarios = scenario_inventory(
            manifest, snapshot, set(delivery["questions"])
        )
        if delivery.get("verificationInventoryHash") != digest(expected_scenarios):
            raise JobError("Delivery scenario inventory does not match declared checks")
        canonical = {
            k: v for k, v in delivery.items() if k not in ("deliveryHash", "_root")
        }
        if digest(canonical) != delivery["deliveryHash"]:
            raise JobError("Delivery manifest content hash mismatch")
        if (
            delivery.get("sourceSnapshotHash") != manifest["sourceSnapshotHash"]
            or delivery.get("inventoryHash") != manifest["inventoryHash"]
        ):
            raise JobError("Delivery does not match source/check inventory")
        native = Path(delivery.get("_root", ""))
        if not native.is_dir() or native.resolve() != native.absolute():
            raise JobError("Actual native delivery root is required")
        for filename, expected_hash in delivery.get("files", {}).items():
            file = safe(native, filename)
            if (
                not file.is_file()
                or hashlib.sha256(file.read_bytes()).hexdigest() != expected_hash
            ):
                raise JobError("Native delivery file hash mismatch: " + filename)
        question = safe(native, "questions/" + id)
        info = json.loads(safe(question, "info.json").read_text())
        if info.get("externalGradingOptions", {}).get("image") != job["imageDigest"]:
            raise JobError(
                "Exported runtime image differs from verification image; export a fresh delivery"
            )
        actual = json.loads(safe(question, "tests/grading-job.json").read_text())
        if actual != grading:
            raise JobError(
                "Exported grading descriptor/profile differs from selected check"
            )
        for x in tests:
            f = safe(question, "tests/" + x["submissionRelativePath"])
            if (
                not f.is_file()
                or hashlib.sha256(f.read_bytes()).hexdigest() != x["sha256"]
            ):
                raise JobError("Exported trusted suite differs from snapshot")
        for x in sources:
            f = safe(
                question, "serverFilesQuestion/starter/" + x["submissionRelativePath"]
            )
            if (
                not f.is_file()
                or hashlib.sha256(f.read_bytes()).hexdigest() != x["sha256"]
            ):
                raise JobError("Exported starter differs from snapshot")
    validate("grading-job", job)
    job.root = Path(tempfile.mkdtemp(prefix="grading-job-"))
    for folder, selection in [("student", selected), ("tests", tests)]:
        (job.root / folder).mkdir(exist_ok=True)
        for x in selection:
            if (
                folder == "student"
                and generated_archive is not None
                and x["submissionRelativePath"] not in primary_names
            ):
                continue
            target = safe(job.root, folder + "/" + x["submissionRelativePath"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(safe(project, x["projectRelativePath"]).read_bytes())
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
            target = safe(publicroot, "tests/" + x["submissionRelativePath"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(safe(project, x["projectRelativePath"]).read_bytes())
        cfg = dict(
            grading,
            testFiles=[x["submissionRelativePath"] for x in public],
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


def _prepared_build_input_hash(job):
    """Hash captured/materialized bytes, independently of the returned proof."""
    config = job["grading"]
    root = job.root
    files = {}
    for name in config["sourceFiles"]:
        path = safe(root / "student", name)
        if (
            not path.exists()
            and config.get("additionalJavaSources", {}).get("primaryRequired", True)
            is False
        ):
            continue
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    selected = {x["submissionRelativePath"]: x["sha256"] for x in job["sources"]}
    if any(selected.get(name) != sha for name, sha in files.items()):
        raise JobError("Materialized native source differs from captured selection")
    if "additionalJavaSources" in config:
        archive = config["additionalJavaSources"]["archive"]
        archive_file = safe(root / "student", archive)
        if archive_file.exists():
            actual = hashlib.sha256(archive_file.read_bytes()).hexdigest()
            expected = selected.get(
                archive, job["sourceHashes"].get("$generated/" + archive)
            )
            if expected is None or expected != actual:
                raise JobError(
                    "Materialized native archive differs from captured selection"
                )
        # Reuse the existing closed ZIP admission; never add another parser.
        spec = importlib.util.spec_from_file_location(
            "native_source_admission", ROOT / "images/java25-grader/grade.py"
        )
        admission = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(admission)
        try:
            extras, _ = admission._additional_inventory(root, config)
        except admission._AdditionalSubmissionError:
            return None  # No build is permitted; retain existing unsafe-submission outcome.
        for name, data in extras:
            if name in files:
                raise JobError("Duplicate selected native source")
            files[name] = hashlib.sha256(data).hexdigest()
            if name in selected and selected[name] != files[name]:
                raise JobError("Materialized native extra source differs from capture")
        if set(selected) - set(files) - {archive}:
            raise JobError("Captured native additional source is missing")
    return digest({"sources": files, "javaBuild": config["javaBuild"]})


def _validate_build_observation(
    result, dependency_hash, input_hash=None, artifact=None
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
    if negative and proof.get("status") != "not-run":
        raise JobError("Compile/API negative cannot claim a build")
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
        if proof.get("dependencyHash") != dependency_hash:
            raise JobError("Build dependency closure differs from execution")
        if input_hash is not None and proof.get("inputHash") != input_hash:
            raise JobError("Build input differs from selected scenario bytes")
        if (
            artifact is not None
            and proof.get("artifact", {}).get("path") != "build/libs/" + artifact
        ):
            raise JobError("Build artifact differs from descriptor")
    return proof


def run_job(job, backend="host", registry=None):
    validate("grading-job", job)
    if not getattr(job, "root", None):
        raise JobError("Prepared private job root required")
    common = {
        k: job[k]
        for k in (
            "scope",
            "qualifiedId",
            "scenario",
            "sourceSnapshotHash",
            "inventoryHash",
            "runtime",
            "imageDigest",
            "sourceHashes",
            "testsHashes",
        )
    }
    if "deliveryHash" in job:
        common["deliveryHash"] = job["deliveryHash"]
    native = job["runtime"] == NATIVE_RUNTIME
    selected_input = _prepared_build_input_hash(job) if native else None
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
                raise JobError("Outer Docker timeout; container removed") from error
            if p.returncode not in (0, 2):
                raise JobError("Docker infrastructure failure: " + p.stderr)
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
                **({"inputHash": selected_input} if selected_input is not None else {}),
            }
        if selected_input != _prepared_build_input_hash(job):
            raise JobError("Selected native scenario inputs changed during execution")
        _validate_build_observation(
            result,
            runtime_evidence(job["runtime"], registry)["dependencyHash"],
            selected_input,
            job["grading"]["javaBuild"]["artifact"],
        )
    if (job.root / "public-verification").is_dir() and result.get(
        "infrastructure"
    ) == "complete":
        publicjob = GradingJob(job)
        publicjob.root = job.root / "public-verification"
        publicresult = run_job(publicjob, backend, registry)
        result["publicResult"] = {
            k: v
            for k, v in publicresult.items()
            if k
            not in {
                "schemaVersion",
                "scope",
                "qualifiedId",
                "scenario",
                "sourceSnapshotHash",
                "inventoryHash",
                "deliveryHash",
                "runtime",
                "imageDigest",
                "sourceHashes",
                "testsHashes",
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
                            "executionEvidence",
                        )
                        if key in result
                    }
                    if native
                    else {}
                ),
            }
    if result.get("infrastructure") == "complete" and result.get(
        "executionEvidence"
    ) != runtime_evidence(job["runtime"], registry):
        raise JobError(
            "Executed image dependency closure differs from prepared runtime"
        )
    value = {"schemaVersion": 1, "backend": backend, **common, **result}
    validate("check-result", value)
    return value


def preserve_build_logs(job, output):
    """Keep private operator logs/receipts before check-course removes scratch."""
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
        base, digest({"qualifiedId": job["qualifiedId"], "scenario": job["scenario"]})
    )
    destination.mkdir(mode=0o700)
    files = {}
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
            files[copy.relative_to(destination).as_posix()] = hashlib.sha256(
                data
            ).hexdigest()
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
    results, expectations, required_scenarios=None, unavailable=None, registry=None
):
    if not results:
        raise JobError("No results; empty receipt forbidden")
    first = results[0]
    status = 0
    checks = []
    bindings = {}
    runtimes = {}
    closures = {}
    observed = set()
    for r in results:
        validate("check-result", r)
        for k in (
            "scope",
            "sourceSnapshotHash",
            "inventoryHash",
            "deliveryHash",
            "backend",
        ):
            if r.get(k) != first.get(k):
                raise JobError("Mixed snapshot/scope receipts forbidden")
        rid = r["runtime"]
        image = r["imageDigest"]
        q = r["qualifiedId"]
        key = (q, r["scenario"])
        if key in observed:
            raise JobError("Duplicate scenario result")
        observed.add(key)
        if rid in runtimes and runtimes[rid] != image:
            raise JobError("Mixed images for one runtime")
        runtimes[rid] = image
        expected_evidence = runtime_evidence(rid, registry)
        evidence = r.get("executionEvidence", expected_evidence)
        if evidence != expected_evidence:
            raise JobError("Executed runtime dependency closure differs from registry")
        if rid == NATIVE_RUNTIME:
            primary_build = _validate_build_observation(r, evidence["dependencyHash"])
            if "publicResult" in r:
                public_evidence = r["publicResult"].get("executionEvidence")
                if (
                    r["publicResult"].get("infrastructure") == "complete"
                    or public_evidence is not None
                ) and public_evidence != expected_evidence:
                    raise JobError(
                        "Public execution dependency closure differs from registry"
                    )
                public_build = _validate_build_observation(
                    r["publicResult"], evidence["dependencyHash"]
                )
                if public_build.get("inputHash") != primary_build.get("inputHash"):
                    raise JobError(
                        "Public build input differs from primary scenario input"
                    )
                if (
                    primary_build["status"] == "success"
                    and public_build["status"] == "success"
                    and public_build["artifact"]["path"]
                    != primary_build["artifact"]["path"]
                ):
                    raise JobError(
                        "Public build artifact differs from primary descriptor"
                    )
        binding = {
            "qualifiedId": q,
            "runtime": rid,
            "imageDigest": image,
            "dependencyHash": evidence["dependencyHash"],
        }
        if q in bindings and bindings[q] != binding:
            raise JobError("Mixed runtime/image for one question")
        bindings[q] = binding
        closures[rid] = evidence
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
    receipt = {
        "schemaVersion": 1,
        "toolVersion": TOOL_VERSION,
        "backend": first["backend"],
        "scope": first["scope"],
        "sourceSnapshotHash": first["sourceSnapshotHash"],
        "inventoryHash": first["inventoryHash"],
        "status": ["success", "defect", "infrastructure-failure"][status],
        "exitCode": status,
        "coverage": "complete" if complete else "partial",
        "scenarioInventory": required,
        "scenarioInventoryHash": digest(required),
        "unavailableReferences": unavailable,
        "checkedIds": sorted(bindings),
        "questionBindings": [bindings[q] for q in sorted(bindings)],
        "runtimes": runtimes,
        "runtimeEvidence": closures,
        "dependencyHashes": {
            rid + "/" + name: sha
            for rid, closure in closures.items()
            for name, sha in closure["dependencyHashes"].items()
        },
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
        receipt["buildEvidence"] = sorted(
            native_builds, key=lambda r: (r["qualifiedId"], r["scenario"])
        )
    if "deliveryHash" in first:
        receipt["deliveryHash"] = first["deliveryHash"]
    receipt["identityHash"] = digest(receipt)
    validate_receipt_integrity(receipt)
    return receipt


def validate_receipt_integrity(receipt):
    validate("verification-receipt", receipt)
    if receipt["identityHash"] != digest(
        {k: v for k, v in receipt.items() if k != "identityHash"}
    ):
        raise JobError("Receipt identity mismatch")
    if receipt["scenarioInventoryHash"] != digest(receipt["scenarioInventory"]):
        raise JobError("Receipt scenario inventory hash mismatch")
    required = {
        (r["qualifiedId"], r["scenario"]): r for r in receipt["scenarioInventory"]
    }
    observed = {(r["qualifiedId"], r["scenario"]) for r in receipt["expectations"]}
    absent = {
        (r["qualifiedId"], r["scenario"]) for r in receipt["unavailableReferences"]
    }
    if (
        len(required) != len(receipt["scenarioInventory"])
        or len(observed) != len(receipt["expectations"])
        or len(absent) != len(receipt["unavailableReferences"])
    ):
        raise JobError("Duplicate receipt scenario observation")
    if absent & observed or any(
        key not in required
        or not required[key]["optional"]
        or not key[1].startswith("reference:")
        for key in absent
    ):
        raise JobError("Invalid optional-reference absence")
    if required and not observed <= set(required):
        raise JobError("Receipt contains undeclared scenarios")
    if receipt["coverage"] == "complete" and (
        not required or observed | absent != set(required)
    ):
        raise JobError("Receipt falsely claims complete coverage")
    bindings = {r["qualifiedId"]: r for r in receipt["questionBindings"]}
    if (
        len(bindings) != len(receipt["questionBindings"])
        or set(bindings) != set(receipt["checkedIds"])
        or {q for q, s in observed} != set(bindings)
    ):
        raise JobError("Receipt question bindings differ from observations")
    builds = receipt.get("buildEvidence", [])
    build_keys = {(r["qualifiedId"], r["scenario"]) for r in builds}
    native_keys = {
        (q, s) for q, s in observed if bindings[q]["runtime"] == NATIVE_RUNTIME
    }
    if len(build_keys) != len(builds) or build_keys != native_keys:
        raise JobError(
            "Native receipt build coverage differs from scenario observations"
        )
    if not native_keys and "buildEvidence" in receipt:
        raise JobError("Legacy receipt cannot contain native build evidence")
    observations = {
        (row["qualifiedId"], row["scenario"]): row for row in receipt["expectations"]
    }
    for proof in builds:
        inner = {
            key: value
            for key, value in proof.items()
            if key not in ("qualifiedId", "scenario", "outcome")
        }
        _validate_build_observation(
            {**proof["outcome"], "buildEvidence": inner},
            bindings[proof["qualifiedId"]]["dependencyHash"],
        )
        observation = observations[(proof["qualifiedId"], proof["scenario"])]
        if observation["matched"] and proof["outcome"]["infrastructure"] != "complete":
            raise JobError(
                "Matched native receipt cannot contain infrastructure failure"
            )
        if (
            proof["scenario"].startswith("reference:")
            and observation["matched"]
            and proof["status"] != "success"
        ):
            raise JobError(
                "Matched reference requires successful native build evidence"
            )
        if receipt["status"] == "success" and proof["status"] == "failure":
            raise JobError("Successful receipt cannot contain trusted build failure")
    used = {}
    for binding in bindings.values():
        rid = binding["runtime"]
        closure = receipt["runtimeEvidence"].get(rid)
        if (
            not closure
            or digest(closure["dependencyHashes"]) != closure["dependencyHash"]
            or closure["dependencyHash"] != binding["dependencyHash"]
            or receipt["runtimes"].get(rid) != binding["imageDigest"]
        ):
            raise JobError("Receipt runtime binding is inconsistent")
        used[rid] = closure
    if set(used) != set(receipt["runtimes"]) or set(used) != set(
        receipt["runtimeEvidence"]
    ):
        raise JobError("Receipt has unbound runtime evidence")
    if {
        rid + "/" + name: sha
        for rid, closure in used.items()
        for name, sha in closure["dependencyHashes"].items()
    } != receipt["dependencyHashes"]:
        raise JobError("Receipt flattened dependency closure is inconsistent")


def _validate_automatic_release_receipt(receipt, delivery, native, registry=None):
    if delivery.get("schemaVersion") != 3:
        raise JobError("Unsupported native delivery; v3 required")
    validate_receipt_integrity(receipt)
    if receipt["identityHash"] != digest(
        {k: v for k, v in receipt.items() if k != "identityHash"}
    ):
        raise JobError("Receipt identity mismatch")
    for field in ("deliveryHash", "sourceSnapshotHash", "inventoryHash"):
        if receipt[field] != delivery.get(field):
            raise JobError("Receipt source/delivery identity differs")
    if (
        receipt["scope"] != "delivery"
        or receipt["backend"] != "container"
        or receipt["status"] != "success"
        or receipt["coverage"] != "complete"
    ):
        raise JobError("A complete authoritative delivery receipt is required")
    if delivery.get("candidate") is True:
        raise JobError("Local image candidate cannot be staged")
    if digest(
        {k: v for k, v in delivery.items() if k != "deliveryHash"}
    ) != delivery.get("deliveryHash"):
        raise JobError("Delivery identity mismatch")
    if (
        digest(receipt["scenarioInventory"])
        != delivery.get("verificationInventoryHash")
        or receipt["scenarioInventoryHash"] != delivery["verificationInventoryHash"]
    ):
        raise JobError("Declared scenario inventory is not bound to delivery")
    expected = {(r["qualifiedId"], r["scenario"]) for r in receipt["scenarioInventory"]}
    observed = {(r["qualifiedId"], r["scenario"]) for r in receipt["expectations"]}
    unavailable = {
        (r["qualifiedId"], r["scenario"]) for r in receipt["unavailableReferences"]
    }
    optional = {
        (r["qualifiedId"], r["scenario"])
        for r in receipt["scenarioInventory"]
        if r["optional"] and r["scenario"].startswith("reference:")
    }
    if (
        len(expected) != len(receipt["scenarioInventory"])
        or len(observed) != len(receipt["expectations"])
        or len(unavailable) != len(receipt["unavailableReferences"])
    ):
        raise JobError("Duplicate scenario coverage observation")
    if (
        not unavailable <= optional
        or observed & unavailable
        or observed | unavailable != expected
        or any(not r["matched"] for r in receipt["expectations"])
    ):
        raise JobError("Required scenario coverage is incomplete")
    from delivery_verification import classification

    ids = {q for q, method in classification(delivery).items() if method != "manual"}
    if set(receipt["checkedIds"]) != ids or {q for q, s in expected} != ids:
        raise JobError("Question coverage differs from delivery")
    bindings = {r["qualifiedId"]: r for r in receipt["questionBindings"]}
    if len(bindings) != len(receipt["questionBindings"]) or set(bindings) != ids:
        raise JobError("Runtime binding coverage differs from delivery")
    registry = registry or load_runtime_registry()
    used = {}
    for q, binding in bindings.items():
        question = safe(Path(native), "questions/" + q)
        info = json.loads(safe(question, "info.json").read_text())
        descriptor = json.loads(safe(question, "tests/grading-job.json").read_text())
        validate("grading-descriptor", descriptor)
        rid = descriptor["runtime"]
        image = info.get("externalGradingOptions", {}).get("image")
        if (
            rid != binding["runtime"]
            or image != binding["imageDigest"]
            or receipt["runtimes"].get(rid) != image
        ):
            raise JobError("Question runtime/image differs from receipt")
        if (
            not isinstance(image, str)
            or not __import__("re").fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", image)
            or registry["profiles"][rid]["image"] != image
        ):
            raise JobError("Published runtime registry does not match question image")
        evidence = runtime_evidence(rid, registry)
        if (
            evidence != receipt["runtimeEvidence"].get(rid)
            or evidence["dependencyHash"] != binding["dependencyHash"]
        ):
            raise JobError("Question runtime dependency closure differs from receipt")
        if rid == NATIVE_RUNTIME:
            for proof in receipt.get("buildEvidence", []):
                if (
                    proof["qualifiedId"] == q
                    and proof["status"] == "success"
                    and proof["artifact"]["path"]
                    != "build/libs/" + descriptor["javaBuild"]["artifact"]
                ):
                    raise JobError(
                        "Receipt native artifact differs from actual descriptor"
                    )
        used[rid] = evidence
    if set(used) != set(receipt["runtimes"]) or set(used) != set(
        receipt["runtimeEvidence"]
    ):
        raise JobError("Receipt runtime set differs from actual question runtimes")
    flattened = {
        rid + "/" + name: sha
        for rid, closure in used.items()
        for name, sha in closure["dependencyHashes"].items()
    }
    if flattened != receipt["dependencyHashes"]:
        raise JobError("Receipt dependency hashes differ from runtime closure")
    for name, sha in delivery.get("files", {}).items():
        if hashlib.sha256(safe(Path(native), name).read_bytes()).hexdigest() != sha:
            raise JobError("Native payload differs from canonical delivery")


def validate_release_receipt(receipt, delivery, native, registry=None):
    from delivery_verification import classification, package_integrity

    validate("delivery-verification-receipt", receipt)
    methods = classification(delivery)
    if receipt["identityHash"] != digest(
        {k: v for k, v in receipt.items() if k != "identityHash"}
    ):
        raise JobError("Outer receipt identity mismatch")
    if delivery.get("candidate") is True:
        raise JobError("Local image candidate cannot be staged")
    for key in ("deliveryHash", "sourceSnapshotHash", "inventoryHash"):
        if receipt[key] != delivery.get(key):
            raise JobError("Outer receipt source/delivery identity differs")
    if receipt["packageIntegrity"] != package_integrity(delivery, native):
        raise JobError("Actual package differs from receipt")
    automatic = {q for q, method in methods.items() if method != "manual"}
    if automatic:
        if receipt["automatic"]["state"] != "verified":
            raise JobError("Automatic questions require nonempty executed proof")
        _validate_automatic_release_receipt(
            receipt["automatic"]["receipt"], delivery, native, registry
        )
    elif receipt["automatic"] != {
        "state": "not-applicable",
        "reason": "all-questions-manual",
    }:
        raise JobError("Wholly manual proof cannot fabricate automatic execution")
