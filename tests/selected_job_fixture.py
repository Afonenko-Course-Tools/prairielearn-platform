"""Краткие функциональные fixtures приватного selected-files договора."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import FunctionType
from typing import TYPE_CHECKING, Protocol, TypeGuard, runtime_checkable
import unittest

if TYPE_CHECKING:
    from grading_job import GradingJob
    from grading_types import CheckResult


def _object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _record(value: object) -> TypeGuard[dict[str, object]]:
    return _object(value) and all(isinstance(key, str) for key in value)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def fixture_record(value: object) -> dict[str, object]:
    """Тот же mutable dict, без проверки валидности предметного DTO."""
    if not _record(value):
        raise AssertionError("Fixture должен содержать строковые ключи объекта")
    return value


def fixture_list(value: object) -> list[object]:
    if not _list(value):
        raise AssertionError("Fixture должен содержать список")
    return value


def fixture_text(value: object) -> str:
    if not isinstance(value, str):
        raise AssertionError("Fixture должен содержать строку")
    return value


class _JobOwner(Protocol):
    @property
    def job(self) -> Path: ...

    @property
    def cfg(self) -> Mapping[str, object]: ...


@runtime_checkable
class _SetupAlias(Protocol):
    def __call__(_self, self: unittest.TestCase) -> None: ...
    def __get__(
        self, instance: unittest.TestCase, owner: type[object] | None = None, /
    ) -> Callable[[], None]: ...


@runtime_checkable
class _RunAlias(Protocol):
    def __call__(self, case: _JobOwner, /) -> dict[str, object]: ...
    def __get__(
        self, instance: _JobOwner, owner: type[object] | None = None, /
    ) -> Callable[[], dict[str, object]]: ...


def fixture_set_up(value: object) -> _SetupAlias:
    # JUnitJob.setUp использует только TestCase.addCleanup и создаёт tmp/job/cfg.
    # Никакого nominal JUnitJob состояния до вызова ему не требуется.
    if not isinstance(value, _SetupAlias) or not isinstance(value, FunctionType):
        raise AssertionError("Fixture setup должен быть прежней unbound функцией")
    return value


def fixture_run_job(value: object) -> _RunAlias:
    # JUnitJob.run_job читает job/cfg, сериализует исходный cfg и вызывает grade.
    # Здесь нет wrapper: сохраняются function identity и descriptor binding.
    if not isinstance(value, _RunAlias) or not isinstance(value, FunctionType):
        raise AssertionError("Fixture run_job должен быть прежней unbound функцией")
    return value


@runtime_checkable
class GradingJobs(Protocol):
    JobError: type[Exception]

    def validate(self, name: str, value: object) -> None: ...
    def validate_profile(self, check: object) -> None: ...
    def prepare_job(
        self,
        manifest: object,
        snapshot: str | Path | None,
        id: str,
        scenario: str,
        scope: str = "declared",
        delivery: object = None,
        registry: object = None,
    ) -> GradingJob: ...
    def run_job(
        self, job: GradingJob, backend: str = "host", registry: object = None
    ) -> CheckResult: ...


def native_manifest(project: object) -> dict[str, object]:
    project = fixture_record(project)
    project.setdefault(
        "exerciseId", fixture_text(project["qualifiedId"]).split("/")[-1]
    )
    project.setdefault("source", "labs/fixture.qmd")
    project.setdefault("verificationTests", [])
    project.setdefault("contractFixtures", [])
    project.setdefault("readiness", {"ready": True, "missing": []})
    project.setdefault("references", [])
    for value in fixture_list(project["references"]):
        ref = fixture_record(value)
        declaration = next(
            fixture_record(row)
            for row in fixture_list(
                fixture_record(project["check"]).get("references", [])
            )
            if fixture_record(row)["name"] == ref["name"]
        )
        ref.setdefault("root", declaration["root"])
        ref.setdefault("optional", declaration.get("optional", False))
        ref.setdefault("available", True)
        ref.setdefault("group", ref["name"])
        ref.setdefault(
            "targets",
            [fixture_record(row)["target"] for row in fixture_list(ref["sources"])],
        )
    return {
        "schemaVersion": 3,
        "courseId": fixture_text(project["qualifiedId"]).split("/")[0],
        "bookRoot": "tasks",
        "projects": [project],
    }
