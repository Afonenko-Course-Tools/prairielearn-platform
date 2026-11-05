"""Single native RESULTS boundary. Private runner observations never pass through."""

import math
import re
import textwrap


def _prose(value):
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


def student_result(result, descriptor):
    kind = _KINDS.get(result.get("classification"), "infrastructure")
    if result.get("infrastructure") == "failure" or result.get("grading_error"):
        kind = "infrastructure"
    reason, observed, what_check = _EXPLANATIONS[kind]
    subject = descriptor.get("feedback")
    if (
        isinstance(subject, dict)
        and set(subject) == {"requirement", "whatCheck"}
        and all(isinstance(v, str) and 0 < len(v) <= 8192 for v in subject.values())
        and kind not in ("infrastructure", "success")
    ):
        reason += " Проверяемое требование: " + subject["requirement"]
        what_check = subject["whatCheck"]
    feedback = {
        "kind": kind,
        "reason": reason,
        "observed": observed,
        "whatCheck": what_check,
    }
    native = {
        "gradable": kind != "infrastructure",
        "classification": (
            result.get("classification")
            if kind != "infrastructure"
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
    counts = result.get("counts", {})
    if isinstance(counts, dict) and (
        "cases" in counts or "feedbackProtocolVersion" in counts
    ):
        # Fish counts have a separate shape and no JUnit case projection.
        # Every JUnit projection uses the same decoder before reading cases.
        import runpy
        from pathlib import Path

        runpy.run_path(str(Path(__file__).with_name("junit_result.py")))[
            "validate_counts"
        ](
            counts,
            require_cases=not (
                descriptor.get("mode") == "student-tests"
                and counts.get("feedbackProtocolVersion", 1) == 1
            ),
        )
    case_results = counts.get("cases") if isinstance(counts, dict) else None
    has_leaf_results = kind != "infrastructure" and isinstance(case_results, list) and counts.get("complete") is True
    if has_leaf_results:
        feedback["cases"] = []
        native["tests"] = []
        complete = True
        for original in case_results:
            case = {key: original[key] for key in ("name", "status", "expected", "actual") if key in original}
            feedback["cases"].append(case)
            lines = []
            if counts.get("feedbackProtocolVersion") == 2:
                checks = [dict(check) for check in original["checks"]]
                case["checks"] = checks
                if "expected" in case or "actual" in case:
                    case["reporter"] = {"origin": "trusted-TestReporter", **{
                        key: case[key] for key in ("expected", "actual") if key in case}}
                    lines.append("Наблюдение TestReporter:")
                    lines.extend(label + ": " + case.get(key, "не установлено") for key, label in
                                 (("expected", "Ожидается"), ("actual", "Получено")))
                if not checks and case["status"] != "passed":
                    complete = False
                    if not case.get("reporter"):
                        lines.append(_prose("Подробности сравнения не получены: проверка завершилась до поддержанного наблюдения."))
                for check in checks:
                    complete &= check["availability"] == "complete"
                    lines.extend(["Проверка: " + check["property"], "Источник: " + check["site"],
                                  "Ожидается: " + check["expected"], "Получено: " + check["actual"]])
                    if check["availability"] != "complete":
                        lines.append("Полнота: " + check["availability"])
                    for key, label in (("delta", "Допуск"), ("differenceIndex", "Первое различие"),
                                       ("differenceLine", "Строка"), ("differenceColumn", "Столбец"),
                                       ("differenceExpected", "Ожидаемый фрагмент"),
                                       ("differenceActual", "Полученный фрагмент")):
                        if key in check:
                            lines.append(label + ": " + check[key])
            else:
                lines.extend(label + ": " + case.get(key, "не установлено") for key, label in
                             (("expected", "Ожидается"), ("actual", "Получено")))
            summary = "Проверка пройдена." if case["status"] == "passed" else "Проверка не пройдена."
            native["tests"].append({"name": case["name"], "description": summary,
                                    "message": "\n".join([summary, *lines]),
                                    "points": int(case["status"] == "passed"), "max_points": 1})
        if counts.get("feedbackProtocolVersion") == 2:
            feedback["feedbackCompleteness"] = "complete" if complete else "incomplete"
    if kind == "compile":
        diagnostics = result.get("diagnostics", {})
        text = (
            diagnostics.get("studentCompilation", "")
            if isinstance(diagnostics, dict)
            else ""
        )
        errors = []
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
                    declared = descriptor.get("sourceFiles", [])
                    matching = [
                        name
                        for name in declared
                        if isinstance(name, str)
                        and (path == name or path.endswith("/" + name))
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
                    {"file": filename, "line": int(match[2]), "reason": reason}
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
        if all(
            isinstance(diagnostic.get(key), str) for key in ("expected", "observed")
        ):
            feedback["api"] = {
                "expected": diagnostic["expected"][:8192],
                "actual": diagnostic["observed"][:8192],
            }
            native["message"] += (
                " Ожидаемый API: "
                + feedback["api"]["expected"]
                + ". Обнаружено: "
                + feedback["api"]["actual"]
            )
    return native
