"""Закрытые data-only bindings v4; пакет и seed никогда не исполняются."""

import io
import json
import os
import re
import resource
import stat
import subprocess  # nosec B404 # subprocess is the intentional argv process boundary; no shell import shortcut
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from collections.abc import Collection, Sequence
from typing import TypeGuard
from grading_job import JobError
from json_boundary import is_object, is_list
from delivery_types import (
    GradingMethod,
    MatchingOption,
    NativeControl,
    ResponseSlot,
    SeedDeclaration,
    SeedProof,
)


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return is_object(value) and all(isinstance(key, str) for key in value)


def _strings(value: object) -> TypeGuard[list[str]]:
    return is_list(value) and all(isinstance(item, str) for item in value)


def closed(v: object, keys: Sequence[str]) -> None:
    if not is_object(v) or set(v) != set(keys):
        raise JobError("Closed delivery4 binding required")


def _closed(v: object, keys: Sequence[str]) -> dict[str, object]:
    closed(v, keys)
    if not _object(v):
        raise JobError("Closed delivery4 binding required")
    return v


def _option(value: object) -> TypeGuard[MatchingOption]:
    return (
        _object(value)
        and set(value) == {"anchor", "ordinal"}
        and isinstance(value["anchor"], str)
        and isinstance(value["ordinal"], (int, float))
    )


def _options(value: object) -> TypeGuard[list[MatchingOption]]:
    return is_list(value) and all(_option(item) for item in value)


def _slot(value: object) -> TypeGuard[ResponseSlot]:
    if not _object(value) or not {"name", "type", "anchor"} <= value.keys():
        return False
    if (
        not isinstance(value["name"], str)
        or not isinstance(value["anchor"], str)
        or value["type"] not in ("manual", "numeric", "single-choice", "matching")
    ):
        return False
    return (
        ("labelAnchor" not in value or isinstance(value["labelAnchor"], str))
        and ("ordinal" not in value or type(value["ordinal"]) is int)
        and ("options" not in value or _options(value["options"]))
    )


def _slot_list(value: object) -> TypeGuard[list[ResponseSlot]]:
    return is_list(value) and all(_slot(item) for item in value)


def _method(values: Sequence[ResponseSlot]) -> GradingMethod:
    types = {slot["type"] for slot in values}
    return (
        "manual"
        if types == {"manual"}
        else "mixed"
        if "manual" in types
        else "external"
    )


def slots(binding: object) -> list[ResponseSlot]:
    if not _object(binding):
        raise JobError("Closed delivery4 binding required")
    values = binding.get("responseSlots")
    kind = binding.get("answerType")
    if not is_list(values) or not 1 <= len(values) <= 4096:
        raise JobError("Native response slots required")
    if not _slot_list(values):
        raise JobError("Closed unique native slot required")
    anchors: set[str] = set()
    for slot in values:
        if (
            set(slot) - {"name", "type", "anchor", "labelAnchor", "ordinal", "options"}
            or not slot["name"]
            or not slot["anchor"]
            or slot["anchor"] in anchors
        ):
            raise JobError("Closed unique native slot required")
        anchors.add(slot["anchor"])
        if "labelAnchor" in slot and not slot["labelAnchor"]:
            raise JobError("Invalid label anchor")
        if "ordinal" in slot and slot["ordinal"] < 0:
            raise JobError("Invalid ordinal")
        if "options" in slot:
            options = slot["options"]
            if not options:
                raise JobError("Invalid matching options")
            for index, option in enumerate(options):
                if not option["anchor"] or option["ordinal"] != index:
                    raise JobError("Invalid matching option")
            if len({option["anchor"] for option in options}) != len(options):
                raise JobError("Duplicate matching option")
    if kind in ("manual", "numeric"):
        if (
            len(values) != 1
            or values[0]["name"] != "answer"
            or values[0]["type"] != kind
            or set(values[0]) != {"name", "type", "anchor"}
        ):
            raise JobError("Simple slot shape differs")
    elif kind == "single-choice":
        if len(values) < 2 or any(
            slot["name"] != "answer"
            or slot["type"] != kind
            or slot.get("ordinal") != index
            or set(slot) != {"name", "type", "anchor", "ordinal", "labelAnchor"}
            for index, slot in enumerate(values)
        ):
            raise JobError("Choice slot shape differs")
    elif kind == "matching":
        first_options = values[0].get("options")
        if first_options is None or any(
            slot["name"] != "match-" + str(index)
            or slot["type"] != kind
            or slot.get("ordinal") != index
            or set(slot)
            != {"name", "type", "anchor", "ordinal", "labelAnchor", "options"}
            or slot.get("options") != first_options
            for index, slot in enumerate(values)
        ):
            raise JobError("Matching slot shape differs")
    elif kind == "multipart":
        if len({slot["name"] for slot in values}) != len(values) or any(
            slot["type"] not in ("manual", "numeric")
            or set(slot) != {"name", "type", "anchor", "labelAnchor"}
            for slot in values
        ):
            raise JobError("Multipart slot shape differs")
    else:
        raise JobError("Unknown native answer type")
    method = _method(values)
    if binding.get("grading") != {"method": method} or binding.get(
        "upstreamGradingMethod"
    ) != ("Manual" if method == "manual" else "Internal"):
        raise JobError("Native answer grading/slot combination differs")
    return values


def _seed(value: object) -> SeedDeclaration:
    seed = _closed(value, ["schema", "archive", "manifest"])
    if (
        seed["schema"] != "pl-git-workspace-seed-v1"
        or seed["archive"] != "workspace/.pl-seed/starter.zip"
        or seed["manifest"] != "workspace/.pl-seed/manifest.json"
    ):
        raise JobError("Workspace seed binding differs")
    return {
        "schema": "pl-git-workspace-seed-v1",
        "archive": "workspace/.pl-seed/starter.zip",
        "manifest": "workspace/.pl-seed/manifest.json",
    }


def binding4(v: object) -> GradingMethod:
    if not _object(v):
        raise JobError("Unknown delivery4 kind")
    kind = v.get("kind")
    if kind == "native-answer":
        closed(
            v,
            [
                "kind",
                "uuid",
                "grading",
                "answerType",
                "responseSlots",
                "upstreamGradingMethod",
            ],
        )
        return _method(slots(v))
    if kind != "workspace":
        raise JobError("Unknown delivery4 kind")
    closed(
        v,
        [
            "kind",
            "uuid",
            "grading",
            "sourceRoot",
            "submission",
            "seed",
            "upstreamGradingMethod",
            "singleVariant",
        ],
    )
    from delivery_verification import relative_name

    if (
        v["grading"] != {"method": "manual"}
        or v["upstreamGradingMethod"] != "Manual"
        or v["singleVariant"] is not True
        or not relative_name(v["sourceRoot"])
    ):
        raise JobError("Workspace must be single manual project")
    submission = _closed(v["submission"], ["mode", "workspaceOptions"])
    options = submission["workspaceOptions"]
    if (
        submission["mode"] != "workspace"
        or not _object(options)
        or not {"image", "home", "port", "gradedFiles"} <= options.keys()
        or set(options)
        - {"image", "home", "port", "gradedFiles", "rewriteUrl", "enableNetworking"}
    ):
        raise JobError("Closed workspace options required")
    if (
        not isinstance(options["image"], str)
        or not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", options["image"])
        or not isinstance(options["home"], str)
        or not re.fullmatch(r"/(?:[a-zA-Z0-9_-]+/?)+", options["home"])
        or type(options["port"]) is not int
        or not 1024 <= options["port"] <= 65535
    ):
        raise JobError("Workspace runtime binding differs")
    files = options["gradedFiles"]
    required = {
        "work/**",
        "work/.git/**",
        "work/.*",
        "explanation.m[d]",
        ".pl-seed/identity.jso[n]",
    }
    if (
        not _strings(files)
        or not required <= set(files)
        or len(files) != len(set(files))
        or any(not relative_name(name) for name in files)
        or any(
            key in options and type(options[key]) is not bool
            for key in ("rewriteUrl", "enableNetworking")
        )
    ):
        raise JobError("Workspace return inventory differs")
    _seed(v["seed"])
    return "manual"


def _bindings(delivery: object) -> dict[str, dict[str, object]]:
    if not _object(delivery):
        raise JobError("Closed delivery required")
    values = delivery.get("gradingPayloads")
    if not _object(values):
        raise JobError("Exact grading binding catalog required")
    bindings: dict[str, dict[str, object]] = {}
    for question, value in values.items():
        if not _object(value):
            raise JobError("Closed delivery4 binding required")
        bindings[question] = value
    return bindings


def code_ids(delivery: object) -> set[str]:
    from delivery_verification import classification

    methods = classification(delivery)
    bindings = _bindings(delivery)
    return {
        question
        for question, method in methods.items()
        if method != "manual" and bindings[question]["kind"] == "project"
    }


def native_proof(
    q: str,
    b: object,
    question_files: Collection[str],
    controls: Sequence[NativeControl],
) -> None:
    expected: list[tuple[str, str, str]] = []
    for slot in slots(b):
        value = (
            ("pl-rich-text-editor", "file-name", slot["name"] + ".html")
            if slot["type"] == "manual"
            else ("pl-string-input", "answers-name", slot["name"])
        )
        if value not in expected:
            expected.append(value)
    actual: list[tuple[str, str, str | None]] = []
    for tag, attrs in controls:
        if tag in ("pl-string-input", "pl-rich-text-editor"):
            key = "file-name" if tag == "pl-rich-text-editor" else "answers-name"
            actual.append((tag, key, attrs.get(key)))
        elif tag != "pl-question-panel":
            raise JobError("Native answer contains unbound controls")
        if (
            tag == "pl-string-input"
            and set(attrs) != {"answers-name", "allow-blank"}
            or tag == "pl-string-input"
            and attrs.get("allow-blank") != "true"
            or tag == "pl-rich-text-editor"
            and set(attrs) != {"file-name", "placeholder"}
        ):
            raise JobError("Native answer control attributes differ")
    if actual != expected or any("correct" in attrs for _, attrs in controls):
        raise JobError("Native controls differ from public response slots")
    if "server.py" not in question_files or any(
        name.startswith("tests/") or name in ("server.js", "server.ts")
        for name in question_files
    ):
        raise JobError("Native answer cannot contain code Job")


def seed_proof(native: str | Path, prefix: str, b: object) -> SeedProof:
    from delivery_verification import file_bytes, relative_name

    if not _object(b):
        raise JobError("Workspace seed binding differs")
    seed = _seed(b.get("seed"))
    raw = file_bytes(native, prefix + seed["archive"])
    manifest_raw = file_bytes(native, prefix + seed["manifest"])
    if len(raw) > 64 * 1024**2 or len(manifest_raw) > 2 * 1024**2:
        raise JobError("Seed bound exceeded")
    manifest = _closed(json.loads(manifest_raw), ["schema", "files"])
    files = manifest["files"]
    if manifest["schema"] != seed["schema"] or not _strings(files) or not files:
        raise JobError("Seed manifest differs")
    expected: set[str] = set()
    for name in files:
        if not relative_name(name) or name in expected:
            raise JobError("Seed paths invalid")
        expected.add(name)
    entries: dict[str, bytes] = {}
    aliases: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if not 1 <= len(z.infolist()) <= 4096:
                raise JobError("Seed count exceeded")
            for f in z.infolist():
                name = f.filename
                mode = f.external_attr >> 16
                alias = unicodedata.normalize("NFC", name).casefold()
                if (
                    not relative_name(name)
                    or name in entries
                    or alias in aliases
                    or f.is_dir()
                    or f.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or f.file_size > 8 * 1024**2
                ):
                    raise JobError("Unsafe seed entry")
                total += f.file_size
                if total > 64 * 1024**2:
                    raise JobError("Expanded seed bound exceeded")
                data = z.read(f)
                entries[name] = data
                aliases.add(alias)
    except (zipfile.BadZipFile, RuntimeError) as e:
        raise JobError("Invalid seed ZIP") from e
    if set(entries) != expected:
        raise JobError("Seed selected paths differ")
    # Public materialization copies must agree byte-for-byte with seed entries.
    for n, data in entries.items():
        if (
            "/.git/" not in "/" + n
            and file_bytes(native, prefix + "clientFilesQuestion/starter/" + n) != data
        ):
            raise JobError("Seed/source common file differs")
    if file_bytes(native, prefix + "clientFilesQuestion/starter.zip") != raw:
        raise JobError("Workspace public ZIP differs from seed")
    required = {"work/.git/HEAD", "work/.git/config", "work/.git/index"}
    if (
        not required <= entries.keys()
        or entries["work/.git/HEAD"] != b"ref: refs/heads/main\n"
    ):
        raise JobError("Initial Git main state required")
    import configparser

    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(entries["work/.git/config"].decode())
    except (ValueError, configparser.Error) as e:
        raise JobError("Invalid Git config") from e
    if (
        set(config.sections()) != {"core"}
        or set(config["core"])
        - {
            "repositoryformatversion",
            "filemode",
            "bare",
            "logallrefupdates",
            "autocrlf",
        }
        or config["core"].get("bare") != "false"
        or config["core"].get("repositoryformatversion") != "0"
        or config["core"].get("autocrlf", "false") != "false"
    ):
        raise JobError("Unsafe initial Git config")
    if any(
        n.startswith("work/.git/refs/")
        and n != "work/.git/refs/heads/main"
        or n
        in (
            "work/.git/commondir",
            "work/.git/objects/info/alternates",
            "work/.git/packed-refs",
        )
        for n in entries
    ):
        raise JobError("External Git state refused")
    # Git читает собственные object/index форматы в изолированной временной копии.
    # Содержимое seed не исполняется; внешние конфиги и Git environment отключены.
    if any(n in entries for n in ("work/.git/info/grafts", "work/.git/shallow")):
        raise JobError("External Git history refused")
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
    )
    with tempfile.TemporaryDirectory(prefix="platform-seed-") as temporary:
        root = Path(temporary)
        for name, data in entries.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        object_limit = 8 * 1024**2

        def limits() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
            resource.setrlimit(resource.RLIMIT_FSIZE, (object_limit, object_limit))
            resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        def git(*args: str) -> bytes:
            try:
                # Файл и OS limit ограничивают stdout до чтения в Python; stderr не копится.
                with tempfile.TemporaryFile() as output:
                    subprocess.run(  # nosec B603, B607 # explicit argv sequence is passed without shell; execution belongs to this component; system tools are intentionally resolved through the operator-controlled PATH (AGENTS.md)
                        [
                            "git",
                            "-c",
                            "core.hooksPath=/dev/null",
                            "-c",
                            "core.fsmonitor=false",
                            *args,
                        ],
                        cwd=root / "work",
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                        check=True,
                        timeout=20,
                        preexec_fn=limits,
                    )
                    output.seek(0)
                    value = output.read(object_limit + 1)
                    if len(value) > object_limit:
                        raise JobError("Git output bound exceeded")
                    return value
            except (OSError, subprocess.SubprocessError) as error:
                raise JobError("Invalid initial Git repository: " + args[0]) from error

        # Native metadata включает недостижимые и packed объекты; до fsck/content.
        objects = git(
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objectsize)",
        ).splitlines()
        stored: set[bytes] = set()
        for row in objects:
            oid, size = row.split()
            if not size.isdigit():
                raise JobError("Invalid Git object metadata")
            if int(size) > object_limit:
                raise JobError("Git object size bound exceeded")
            stored.add(oid)
        git("fsck", "--full", "--no-reflogs")
        if (
            git("symbolic-ref", "HEAD").strip() != b"refs/heads/main"
            or git("rev-list", "--count", "--all").strip() != b"1"
        ):
            raise JobError("Initial Git root commit required")
        ref = git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        git("diff-index", "--cached", "--quiet", "HEAD", "--")
        tracked: set[str] = set()
        for row in git("ls-tree", "-r", "-z", "--full-tree", "HEAD").split(b"\0"):
            if not row:
                continue
            metadata, raw_name = row.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            name = raw_name.decode("utf-8")
            if (
                not relative_name(name)
                or mode not in (b"100644", b"100755")
                or kind != b"blob"
            ):
                raise JobError("Unsafe Git tree path/mode")
            if entries.get("work/" + name) != git("cat-file", "blob", oid.decode()):
                raise JobError("Git worktree differs")
            tracked.add(name)
        if (
            not tracked
            or {
                n[5:]
                for n in entries
                if n.startswith("work/") and not n.startswith("work/.git/")
            }
            != tracked
        ):
            raise JobError("Untracked initial worktree files")
        reachable = set(
            git("rev-list", "--objects", "--no-object-names", "HEAD").splitlines()
        )
        if stored != reachable:
            raise JobError("Unbound Git objects")
    return {"initialCommit": ref}


def workspace_image_authority(delivery: object, registry: object) -> None:
    images: set[str] = set()
    for binding in _bindings(delivery).values():
        if binding.get("kind") != "workspace":
            continue
        submission = binding.get("submission")
        if not _object(submission):
            raise JobError("Closed workspace options required")
        options = submission.get("workspaceOptions")
        if not _object(options) or not isinstance(options.get("image"), str):
            raise JobError("Workspace runtime binding differs")
        image = options["image"]
        if not isinstance(image, str):
            raise JobError("Workspace runtime binding differs")
        images.add(image)
    if not images:
        return
    if not _object(registry) or registry.get("schemaVersion") != 2:
        raise JobError(
            "Workspace image authority unqualified; package proof is not image qualification"
        )
    closed(registry, ["schemaVersion", "profiles", "workspaceImages"])
    authority = registry["workspaceImages"]
    if not _object(authority) or set(authority) != {"sp-git-workspace-v1"}:
        raise JobError("Workspace image authority unqualified")
    image = _closed(authority["sp-git-workspace-v1"], ["image"])["image"]
    if (
        not isinstance(image, str)
        or not re.fullmatch(
            r"ghcr\.io/[a-z0-9-]+/sp-git-workspace@sha256:[a-f0-9]{64}", image
        )
        or images != {image}
    ):
        raise JobError("Workspace exact qualified image differs")
