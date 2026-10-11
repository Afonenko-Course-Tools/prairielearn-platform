# Текстовый runtime fish

`fish-git-v1` выполняет один объявленный `.fish` файл из текстового редактора PL.
Ни имя курса, ни имя задания, ни формат входных данных не встроены в grader.
Курс поставляет доверенный `checks.py` и явно перечисленные test data files.
Контракт `project-check` содержит `source-profile`, runtime, тесты и limits;
для fish поля `java` не требуется. Java runtimes по-прежнему требуют JDK 25.

Доверенный `checks.py` предоставляет две функции:

```python
def cases(tests_dir):
    # 1..16 вариантов: относительный безопасный путь -> текст UTF-8 до 64 KiB
    return [{"input.txt": "пример\n"}]

def check(work_dir, inputs):
    # Проверка созданных ответом файлов; bool для каждого критерия
    return [("Содержимое результата", (work_dir / "answer.txt").read_text() == "пример\n")]
```

Проверяющий код является доверенным кодом автора, а не ответом студента.
Он должен безопасно читать созданные студентом файлы: ограничить размер,
не следовать symlinks и возвращать содержательные критерии. В System-Practice
пилоте эти правила и два набора headers находятся в репозитории курса.

Runner проверяет dependency closure, синтаксис fish, а затем запускает ответ
под `sbuser` через официальный Landlock sandbox, без сети. Trusted tests и reports
недоступны student UID. Выполнение ограничено временем и объёмом output;
завершение убивает группу процессов. Weighted/all-pass scoring явно задаёт автор.
Syntax/UTF-8 errors, timeout и неверный результат отделены от инфраструктурного
сбоя; ошибка доверенного checker никогда не выдаётся за обычную оценку 0.

```sh
docker build -f images/fish-git-grader/Dockerfile -t fish-git-grader:candidate .
docker image inspect fish-git-grader:candidate --format '{{.Id}}'
```

Dockerfile использует закреплённый официальный grader base с Landlock и sbuser;
fish, Git, Python и jsonschema устанавливаются в image. Config ID и dependency
hashes необходимо записать при проверке candidate. Публичный digest нового image
пока не назначен: для публикации нужны отдельная сборка/release и полный receipt.
