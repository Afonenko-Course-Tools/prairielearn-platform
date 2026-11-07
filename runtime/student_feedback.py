"""Single native RESULTS boundary. Private runner observations never pass through."""

from __future__ import annotations

import math
import re
import textwrap
from typing import TYPE_CHECKING, Protocol, TypeGuard, runtime_checkable

if TYPE_CHECKING:
    from grading_types import CompileError, PublicCase, PublicFeedback, PublicTest, StudentResult
    from junit_result import JUnitCounts


def _mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return _mapping(value) and all(isinstance(key, str) for key in value)


def _objects(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _strings(value: object) -> TypeGuard[list[str]]:
    return _objects(value) and all(isinstance(item, str) for item in value)


@runtime_checkable
class _CountsValidator(Protocol):
    def __call__(self, counts: object, require_cases: bool = True) -> None: ...


def _checked_counts(value: object, *, require_cases: bool) -> TypeGuard[JUnitCounts]:
    import runpy
    from pathlib import Path

    helpers: dict[str, object] = runpy.run_path(str(Path(__file__).with_name("junit_result.py")))
    validator = helpers.get("validate_counts")
    if not isinstance(validator, _CountsValidator):
        raise RuntimeError("Каноническая проверка JUnit недоступна")
    validator(value, require_cases=require_cases)
    return True


def _prose(value: str) -> str:
    return textwrap.fill(value, width=50, break_long_words=False, break_on_hyphens=False)

_EXPLANATIONS = {
    "compile": (
        "Исходники не скомпилированы.",
        "Компилятор не смог подготовить программу к запуску.",
        "Проверьте синтаксис, имена типов и доступность исходников; повторите публичную команду компиляции.",
    ),
    "runtime": (
        "Программа завершилась с ошибкой во время выполнения.",
        "Запуск начался, но вычисление не завершилось штатно.",
        "Проверьте допустимые индексы, деление и обработку входных данных; воспроизведите публичные примеры.",
    ),
    "timeout": (
        "Программа не завершила проверку за отведённое время.",
        "Выполнение остановлено по пределу времени.",
        "Проверьте завершение циклов и ожидание ввода, затем повторите публичный граничный пример.",
    ),
    "wrong-answer": (
        "Результат не удовлетворяет проверяемому требованию.",
        "Хотя бы одна проверка поведения выявила несоответствие.",
        "Сопоставьте операции и формат результата с условием; начните с публичного обычного и граничного примеров.",
    ),
    "infrastructure": (
        "Проверка недоступна из-за сбоя проверяющей среды.",
        "Среда не получила достоверный результат проверки.",
        "Сохраните ответ и повторите отправку позднее; при повторении сообщите преподавателю.",
    ),
    "success": (
        "Автоматические проверки пройдены.",
        "Проверенный результат соответствует автоматическим требованиям.",
        "Просмотрите публичные результаты; если предусмотрена ручная часть, дождитесь оценки преподавателя.",
    ),
    "output-limit": (
        "Программа превысила предел вывода.",
        "Выполнение остановлено из-за объёма выходных данных.",
        "Проверьте повторный вывод в циклах и печать только требуемого результата.",
    ),
    "submission": (
        "Ответ не удалось безопасно подготовить к проверке.",
        "Состав или интерфейс отправленных файлов не соответствует объявленному способу сдачи.",
        "Проверьте публичные требования к именам, интерфейсу и комплекту файлов.",
    ),
    "test-quality": (
        "Набор тестов не подтвердил требуемое поведение.",
        "Есть пропущенные проверки или не обнаруженное нарушение.",
        "Проверьте, что тесты выполняются и различают корректное и ошибочное поведение.",
    ),
}
_KINDS = {
    "success": "success",
    "student-compilation-failure": "compile",
    "student-runtime-failure": "runtime",
    "student-timeout": "timeout",
    "student-output-overflow": "output-limit",
    "behavior-failure": "wrong-answer",
    "student-test-quality-failure": "test-quality",
    "unsafe-submission": "submission",
    "student-api-mismatch": "submission",
    "infrastructure-failure": "infrastructure",
}


def student_result(result: object, descriptor: object) -> StudentResult:
    if not _object(result):
        raise ValueError("Ожидается объект результата проверки")
    classification = result.get("classification")
    kind = _KINDS.get(classification, "infrastructure") if isinstance(classification, str) else "infrastructure"
    if result.get("infrastructure") == "failure" or result.get("grading_error"):
        kind = "infrastructure"
    if not _object(descriptor):
        if kind != "infrastructure":
            raise ValueError("Ожидается объект описания проверки")
        descriptor = {}
    reason, observed, what_check = _EXPLANATIONS[kind]
    if kind == "infrastructure" and result.get("timed_out") is True:
        limits = descriptor.get("limits")
        limit = limits.get("run-seconds") if _object(limits) else None
        try:
            valid_limit = (
                isinstance(limit, (int, float)) and not isinstance(limit, bool)
                and math.isfinite(limit) and limit > 0
            )
        except OverflowError:
            valid_limit = False
        reason = "Превышен общий лимит выполнения проверок."
        observed = (
            f"Проверки остановлены по лимиту {limit:g} с. Достоверная оценка не получена."
            if valid_limit and isinstance(limit, (int, float)) else
            "Проверки остановлены по общему пределу времени. Достоверная оценка не получена."
        )
        what_check = "Сохраните ответ и повторите отправку; при повторении сообщите преподавателю."
    feedback: PublicFeedback = {
        "kind": kind,
        "reason": reason,
        "observed": observed,
        "whatCheck": what_check,
    }
    native: StudentResult = {
        "gradable": kind != "infrastructure",
        "classification": (
            classification
            if kind != "infrastructure" and isinstance(classification, str)
            else "infrastructure-failure"
        ),
        "feedback": feedback,
        "message": "\n".join(_prose(value) for value in (reason, observed, what_check)),
    }
    admission_failure = (
        result.get("classification")
        in ("student-compilation-failure", "student-api-mismatch")
        and result.get("gradable") is True
        and result.get("score") == 0
    )
    if admission_failure:
        native["score"] = 0
    elif kind in ("compile", "submission"):
        native["gradable"] = False
        native["format_errors"] = native["message"]
    if kind == "infrastructure":
        native["grading_error"] = True
    else:
        score = result.get("score")
        if (
            isinstance(score, (int, float))
            and not isinstance(score, bool)
            and math.isfinite(score)
        ):
            native["score"] = max(0, min(1, score))
    raw_counts = result.get("counts", {})
    counts: JUnitCounts | None = None
    if _object(raw_counts) and ("cases" in raw_counts or "feedbackProtocolVersion" in raw_counts):
        # Перед чтением JUnit cases выполняется прежняя каноническая проверка.
        if _checked_counts(raw_counts, require_cases=not (
            descriptor.get("mode") == "student-tests"
            and raw_counts.get("feedbackProtocolVersion", 1) == 1
        )):
            counts = raw_counts
    if kind != "infrastructure" and counts is not None and counts["complete"]:
        public_cases: list[PublicCase] = []
        public_tests: list[PublicTest] = []
        feedback["cases"] = public_cases
        native["tests"] = public_tests
        for original in counts["cases"]:
            case: PublicCase = {"name": original["name"], "status": original["status"]}
            lines: list[str] = []
            for key, label in (("message", "Сообщение"), ("expected", "Ожидается"),
                               ("actual", "Получено"), ("exceptionType", "Исключение"),
                               ("stackTrace", "Трассировка")):
                if key in original:
                    case[key] = original[key]
                    lines.append(label + ": " + original[key])
            public_cases.append(case)
            summary = "Проверка пройдена." if case["status"] == "passed" else "Проверка не пройдена."
            public_tests.append({"name": case["name"], "description": summary,
                                 "message": "\n".join([summary, *lines]),
                                 "points": int(case["status"] == "passed"), "max_points": 1})
    output = result.get("output")
    if isinstance(output, str) and output and (counts is not None or str(descriptor.get("runtime", "")).startswith("java")):
        native["output"] = output[:65536]
    if kind == "compile":
        diagnostics = result.get("diagnostics", {})
        text = (
            diagnostics.get("studentCompilation", "")
            if _object(diagnostics)
            else ""
        )
        errors: list[CompileError] = []
        if isinstance(text, str):
            for match in re.finditer(
                r"(?m)^([^\n]+\.java):(\d+): error: ([^\n]+)", text
            ):
                path = match[1].strip()
                if path.startswith("/grade/student/"):
                    filename = path[len("/grade/student/") :]
                elif "/additional-sources/" in path:
                    filename = path.split("/additional-sources/", 1)[1]
                else:
                    declared_value = descriptor.get("sourceFiles", [])
                    declared = declared_value if _strings(declared_value) else []
                    matching = [
                        name
                        for name in declared
                        if path == name or path.endswith("/" + name)
                    ]
                    filename = (
                        matching[0] if len(matching) == 1 else path.rsplit("/", 1)[-1]
                    )
                if (
                    not filename
                    or any(part in ("", ".", "..") for part in filename.split("/"))
                    or any(char in filename for char in "\\:\r\n\0")
                ):
                    continue
                detail = match[3]
                reason = "Ошибка в синтаксисе или типах программы."
                if "cannot find symbol" in detail:
                    reason = "Не найден используемый тип, метод или переменная."
                elif "incompatible types" in detail:
                    reason = "Тип значения не соответствует требуемому типу."
                    conversion = re.fullmatch(
                        r"incompatible types: ([\w.$<>\[\]? ,]+) cannot be converted to ([\w.$<>\[\]? ,]+)",
                        detail,
                    )
                    if conversion:
                        reason = (
                            "Нельзя преобразовать "
                            + conversion[1]
                            + " в "
                            + conversion[2]
                            + "."
                        )
                elif detail in (
                    "';' expected",
                    "')' expected",
                    "']' expected",
                    "'}' expected",
                ):
                    reason = "Ожидается " + detail.split(" expected", 1)[0] + "."
                elif "illegal start of expression" in detail:
                    reason = "Недопустимое начало выражения."
                elif "reached end of file while parsing" in detail:
                    reason = "Файл закончился до завершения конструкции."
                elif "missing return statement" in detail:
                    reason = "Метод должен вернуть значение."
                elif "is public, should be declared in a file named" in detail:
                    reason = "Имя файла не соответствует открытому типу."
                errors.append(
                    {"file": filename, "line": int(match[2]), "reason": reason, "message": detail}
                )
                if len(errors) == 5:
                    break
        if errors:
            feedback["compileErrors"] = errors
            native["message"] += "\n\n" + "\n".join(
                _prose(error["file"] + ":" + str(error["line"]) + ": " + error["reason"])
                for error in errors
            )
    if result.get("classification") == "student-api-mismatch":
        diagnostic = result.get("apiDiagnostic", {})
        expected = diagnostic.get("expected") if _object(diagnostic) else None
        observed_api = diagnostic.get("observed") if _object(diagnostic) else None
        if isinstance(expected, str) and isinstance(observed_api, str):
            feedback["api"] = {
                "expected": expected[:8192],
                "actual": observed_api[:8192],
            }
            native["message"] += (
                " Ожидаемый API: "
                + feedback["api"]["expected"]
                + ". Обнаружено: "
                + feedback["api"]["actual"]
            )
    return native
