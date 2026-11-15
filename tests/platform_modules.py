"""Узкие контракты собственных динамически загружаемых Platform entrypoints."""

import importlib.util
from pathlib import Path
import sys
from typing import Protocol, runtime_checkable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from grading_types import JavaOutcome, StudentResult


@runtime_checkable
class JavaGrader(Protocol):
    GraderError: type[Exception]

    def grade(self, job_dir: Path, registry: object = None) -> JavaOutcome: ...
    def main(self) -> int: ...


@runtime_checkable
class FeedbackModule(Protocol):
    def student_result(self, result: object, descriptor: object) -> StudentResult: ...


def load_java_grader(path: Path) -> JavaGrader:
    spec = importlib.util.spec_from_file_location("platform_java_grader", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Загрузчик Java grader недоступен")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not isinstance(module, JavaGrader):
        raise RuntimeError("Публичный контракт Java grader недоступен")
    return module


def load_student_feedback(path: Path) -> FeedbackModule:
    spec = importlib.util.spec_from_file_location("platform_student_feedback", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Загрузчик student feedback недоступен")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not isinstance(module, FeedbackModule):
        raise RuntimeError("Контракт student feedback недоступен")
    return module


def grader_hook(grader: object, name: str) -> object:
    """Частный hook проверяется вызывающим тестом через его точный Protocol."""
    return getattr(grader, name, None)
