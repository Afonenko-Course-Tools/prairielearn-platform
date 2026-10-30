"""Single native RESULTS boundary. Private runner observations never pass through."""

import math

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


def validate_public_cases(cases):
    if not isinstance(cases, list) or len(cases) > 32:
        raise ValueError("Invalid public cases")
    ids = set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case)
            - {"id", "name", "test", "input", "state", "action", "expected"}
            or not {"id", "name", "test", "expected"} <= set(case)
            or not {"input", "state", "action"} & set(case)
        ):
            raise ValueError("Invalid public case fields")
        if (
            any(not isinstance(v, str) or len(v) > 8192 for v in case.values())
            or not case["id"]
            or not case["test"]
            or not case["name"].strip()
            or len(case["name"]) > 256
            or case["id"] in ids
        ):
            raise ValueError("Invalid public case value")
        ids.add(case["id"])
    return cases


def student_result(result, descriptor):
    try:
        cases = validate_public_cases(descriptor.get("publicCases", []))
    except (ValueError, AttributeError):
        return student_result({"classification": "infrastructure-failure"}, {})
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
        "publicCases": [],
    }
    native = {
        "gradable": kind != "infrastructure",
        "classification": (
            result.get("classification")
            if kind != "infrastructure"
            else "infrastructure-failure"
        ),
        "feedback": feedback,
        "message": reason + " " + observed + " " + what_check,
    }
    if kind in ("compile", "submission"):
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
    observations = result.get("publicCaseObservations", [])
    for case in cases:
        # Only the declared trusted test may report this explicitly public case.
        matches = [
            o
            for o in observations
            if isinstance(o, dict)
            and o.get("id") == case["id"]
            and o.get("test") == case["test"]
        ]
        value = {
            key: case[key]
            for key in ("id", "name", "input", "state", "action", "expected")
            if key in case
        }
        value.update(actual=None, status="not-run")
        if (
            len(matches) == 1
            and matches[0].get("status") in ("passed", "failed")
            and isinstance(matches[0].get("actual"), str)
        ):
            value.update(
                actual=matches[0]["actual"][:8192], status=matches[0]["status"]
            )
        feedback["publicCases"].append(value)
    if feedback["publicCases"]:
        labels = {
            "name": "Что проверяется",
            "input": "Вход",
            "state": "Состояние",
            "action": "Действие",
            "expected": "Ожидается",
            "actual": "Получено",
            "status": "Статус",
        }
        statuses = {
            "passed": "пройден",
            "failed": "не пройден",
            "not-run": "не запускался",
        }
        native["tests"] = [
            {
                "name": c["name"],
                "description": "\n".join(
                    labels[k]
                    + ": "
                    + (
                        statuses[c[k]]
                        if k == "status"
                        else "не получен" if c[k] is None else str(c[k])
                    )
                    for k in labels
                    if k in c
                ),
                "message": "Публичный сценарий: " + statuses[c["status"]],
                "points": int(c["status"] == "passed"),
                "max_points": 1,
            }
            for c in feedback["publicCases"]
        ]
    return native
