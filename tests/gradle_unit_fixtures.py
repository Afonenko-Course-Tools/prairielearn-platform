"""Временное дерево публичного runtime без собственных inventories."""

import contextlib
import json
import shutil
import tempfile
from pathlib import Path
import unittest
from collections.abc import Generator
from typing import TypeGuard
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from grading_types import RuntimeRegistry
from json_boundary import is_object, is_list

ROOT = Path(__file__).resolve().parents[1]


def _registry_shape(value: object) -> TypeGuard[RuntimeRegistry]:
    if not is_object(value) or type(value.get("schemaVersion")) is not int:
        return False
    profiles = value.get("profiles")
    if not is_object(profiles):
        return False
    for name, row in profiles.items():
        if not isinstance(name, str) or not is_object(row):
            return False
        if not all(isinstance(row.get(key), str) for key in ("bundle", "mode")):
            return False
        if "image" not in row or not (
            row["image"] is None or isinstance(row["image"], str)
        ):
            return False
        if any(
            key in row and not isinstance(row[key], str)
            for key in ("runner", "baseImage", "upstreamCommit")
        ):
            return False
        if any(
            key in row and type(row[key]) is not int
            for key in ("javaRelease", "assertionFeedbackProtocol")
        ):
            return False
        extensions = row.get("sourceExtensions", [])
        if not is_list(extensions) or any(
            not isinstance(item, str) for item in extensions
        ):
            return False
    if "workspaceImages" in value:
        workspaces = value["workspaceImages"]
        if not is_object(workspaces):
            return False
        for name, row in workspaces.items():
            if (
                not isinstance(name, str)
                or not is_object(row)
                or any(
                    not isinstance(key, str) or not isinstance(item, str)
                    for key, item in row.items()
                )
            ):
                return False
    return True


def registry() -> RuntimeRegistry:
    value: object = json.loads((ROOT / "runtime-profiles.json").read_text())
    if not _registry_shape(value):
        raise ValueError("Некорректная форма runtime profiles fixture")
    for profile in value["profiles"].values():
        profile["image"] = "unit.invalid/synthetic-fixture@sha256:" + "1" * 64
    return value


def write_registry(directory: str | Path) -> Path:
    path = Path(directory) / "unit-runtime-profiles.json"
    path.write_text(json.dumps(registry()))
    return path


def unit_platform(case: unittest.TestCase) -> Path:
    view: object = getattr(case, "_unit_platform_view", None)
    if not isinstance(view, Path):
        view = case.enterContext(platform_tree())
        setattr(case, "_unit_platform_view", view)
    return view


@contextlib.contextmanager
def platform_tree(
    *, java_image: str | None = None, fish_image: str | None = None
) -> Generator[Path, None, None]:
    value = registry()
    for name, profile in value["profiles"].items():
        image = fish_image if name == "fish-git-v1" else java_image
        if image is not None:
            profile["image"] = image
    with tempfile.TemporaryDirectory(prefix="platform-test-view-") as temporary:
        root = Path(temporary)
        for directory in ("runtime", "schemas", "tools"):
            shutil.copytree(
                ROOT / directory,
                root / directory,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for name in (
            "images/java25-grader/grade.py",
            "images/fish-git-grader/grade.py",
            "images.lock.json",
            "VERSION",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        (root / "runtime-profiles.json").write_text(json.dumps(value))
        yield root
