#!/usr/bin/env python3
"""Stage exact native delivery commits and emit a read-only Compose mount override."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess  # nosec B404 # subprocess is the intentional argv process boundary; no shell import shortcut
import sys
import tempfile
from typing import Protocol, TypedDict, runtime_checkable

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from json_boundary import JSONObject  # noqa: E402 — import after the local test/tool path bootstrap
from check_registry import Course, RegistryError, validate_registry, INSTITUTIONS  # noqa: E402 — import after the local test/tool path bootstrap
from grading_job import JobError  # noqa: E402 — import after the local test/tool path bootstrap


@runtime_checkable
class Builder(Protocol):
    BuildError: type[Exception]
    PLATFORM: Path

    def read_json(self, path: Path) -> JSONObject: ...
    def publish_directory(self, source: Path, destination: Path) -> None: ...


class BindOptions(TypedDict):
    create_host_path: bool


class BindMount(TypedDict):
    type: str
    source: str
    target: str
    read_only: bool
    bind: BindOptions


class PLService(TypedDict):
    volumes: list[BindMount]


class Services(TypedDict):
    pl: PLService


class ComposeOverride(TypedDict):
    services: Services


class StageArguments(argparse.Namespace):
    registry: Path
    storage: Path
    compose_output: Path
    images: Path
    institutions: Path


def _load_builder() -> Builder:
    spec = importlib.util.spec_from_file_location(
        "native_builder", TOOLS / "build-course.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Загрузчик локального Python-модуля недоступен")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not isinstance(module, Builder):
        raise RuntimeError("Контракт локального builder недоступен")
    return module


builder = _load_builder()


class StorageError(Exception):
    pass


def git(directory: Path, *args: str) -> str:
    try:
        result = subprocess.run(  # nosec B603, B607 # explicit argv sequence is passed without shell; execution belongs to this component; system tools are intentionally resolved through the operator-controlled PATH (AGENTS.md)
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=directory,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise StorageError(
            f"Exact native Git checkout failed: {directory.name}"
        ) from error
    return result.stdout.strip()


def validate_checkout(path: Path, course: Course) -> None:
    metadata = path / ".git"
    if metadata.is_symlink() or not metadata.is_dir():
        raise StorageError("Native checkout requires a contained real Git directory")
    if (
        path.is_symlink()
        or not path.is_dir()
        or git(path, "rev-parse", "HEAD") != course["commit"]
        or git(path, "remote", "get-url", "origin") != course["repository"]
        or git(path, "status", "--porcelain", "--untracked-files=all")
    ):
        raise StorageError("Existing checkout does not match its clean exact pin")
    try:
        info = builder.read_json(path / "infoCourse.json")
        delivery = builder.read_json(path / "delivery.json")
        if not isinstance(info.get("name"), str):
            raise StorageError("Native course metadata required")
        from delivery_verification import package_integrity

        package_integrity(delivery, path)
        for root, dirs, files in os.walk(path):
            if Path(root) == path:
                dirs[:] = [d for d in dirs if d != ".git"]
            for name in dirs + files:
                entry = Path(root) / name
                if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                    raise StorageError("Unsafe native payload path")
        return None
    except (
        builder.BuildError,
        JobError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        raise StorageError("Invalid native course package") from error


def stage_course(
    course: Course,
    storage: str | Path,
    institutions: object = None,
    images: object = None,
) -> Path:
    try:
        if images is None:
            images = builder.read_json(builder.PLATFORM / "images.lock.json")
        version = "pl-courses-v2" if "institution" in course else "pl-courses-v1"
        validate_registry(
            {"schema": version, "courses": [course]}, images, institutions
        )
        storage = Path(storage).absolute()
        if not storage.is_dir() or storage.resolve() != storage or storage.is_symlink():
            raise StorageError("Storage must be an existing absolute real directory")
        parent = storage / course["id"]
        if parent.is_symlink():
            raise StorageError("Storage course parent must not be a symlink")
        parent.mkdir(exist_ok=True)
        destination = parent / course["commit"]
        if destination.exists() or destination.is_symlink():
            validate_checkout(destination, course)
            return destination
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=parent) as temporary:
            stage = Path(temporary) / "native"
            # The registry URL is validated before invoking Git. Checkout is by
            # object identity, with hooks disabled; no moving branch is trusted.
            git(
                parent, "clone", "--no-checkout", "--", course["repository"], str(stage)
            )
            git(stage, "checkout", "--detach", course["commit"])
            validate_checkout(stage, course)
            builder.publish_directory(stage, destination)
        return destination
    except (
        RegistryError,
        builder.BuildError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        raise StorageError(str(error)) from error


def stage_registry(
    registry: object, images: object, storage: str | Path, institutions: object = None
) -> ComposeOverride:
    courses = validate_registry(registry, images, institutions)
    volumes: list[BindMount] = []
    for course in courses:
        path = stage_course(course, storage, institutions, images)
        volumes.append(
            {
                "type": "bind",
                "source": str(path),
                "target": course["mount"],
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        )
    return {"services": {"pl": {"volumes": volumes}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--compose-output", required=True, type=Path)
    parser.add_argument(
        "--images", type=Path, default=TOOLS.parent / "images.lock.json"
    )
    parser.add_argument("--institutions", type=Path, default=INSTITUTIONS)
    args = parser.parse_args(namespace=StageArguments())
    try:
        registry = builder.read_json(args.registry)
        images = builder.read_json(args.images)
        catalog = (
            builder.read_json(args.institutions)
            if registry.get("schema") == "pl-courses-v2"
            else None
        )
        override = stage_registry(registry, images, args.storage, catalog)
        data = json.dumps(override, indent=2) + "\n"
        if args.compose_output.exists():
            if args.compose_output.read_text() != data:
                raise StorageError(
                    "Compose output exists with different contents; choose a fresh output"
                )
        else:
            with args.compose_output.open("x") as f:
                f.write(data)
    except (StorageError, RegistryError, builder.BuildError, OSError) as error:
        parser.exit(1, f"Course staging rejected: {error}\n")
    print(
        f"Staged {len(override['services']['pl']['volumes'])} exact native deliveries; PL sync remains required"
    )


if __name__ == "__main__":
    main()
