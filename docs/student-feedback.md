# Результат внешней проверки

Штатный grader entrypoint записывает в native `results/results.json` безопасную студенческую проекцию. Один модуль `runtime/student_feedback.py` обслуживает Java и fish. Его hash входит в `sharedFiles` каждого runtime и в private dependency closure.

По умолчанию тесты закрыты: их имена, assertions, stdout/stderr, traces, входы, expected и даже actual student output не передаются студенту. RESULTS содержит русские reason, observed и whatCheck для классов compile/runtime/timeout/wrong-answer/infrastructure, а также успеха и защитных отказов. Сбой проверяющей среды не имеет score и помечается grading_error. Наличие файла не создаёт автоматический успех.

Предметная формулировка задаётся явно из публичного требования:

```yaml
feedback:
  requirement: Сохранить исходный массив и порядок его элементов
  what-check: Сравните исходный массив до и после операции на публичном примере
public-cases:
  - id: normal
    name: Сложение двух обычных чисел
    test: Checks#normal
    action: Сложить 2 и 3
    expected: '5'
  - id: boundary
    name: Пустой ввод даёт пустой результат
    test: Checks#boundary
    input: ''
    expected: ''
```

Это часть существующего project-check, а не новый DSL/runner. `public-cases` — allowlist: уникальные id, короткое явное name (что проверяется), exact test binding, input/state/action и expected. Пустая строка допустима как явный опубликованный вход/результат. Только авторизованные публичные случаи получают actual/status в native tests panel. Без фактического observation статус not-run, actual=null; успешный результат не придумывается.

JUnit использует штатный `TestReporter.publishEntry(Map.of("public-case", "normal", "actual", actual))`. Native adapter связывает entry с реальным `Class#method` и исходом этого же теста. Entries другого метода/закрытого ID не публикуются. Для существующего fish checker необязательный третий элемент `(name, passed, observedText)` даёт наблюдение; exact binding — `caseIndex: name`. Прежние пары `(name, passed)` сохраняют закрытую семантику. Assertion messages не используются как публичное объяснение.

Private host verification вызывает прежний grade(job) и сохраняет наблюдения для аудита. Trusted `check-course` добавляет операторский `--verification` при собственном Docker invocation для такого же private raw receipt. Job descriptor, имена файлов и upload не выбирают этот режим; generated native configuration не передаёт этот флаг. Raw private outputs/receipts хранятся вне student native files, сайта и ZIP. Штатный native вызов без флага всегда sanitizes.

Изменение runner/adapter требует нового проверенного candidate image, согласованных hashes и отдельного External gate. Host CLI tests и synthetic Manual UI не подтверждают выполнение опубликованного старого image или actual Moodle.

## Происхождение ошибки Java

Вложенная JVM использует три exact trusted типа canonical JavaProcess: runtime,
timeout и output limit. Runner сам формирует private trusted-root marker; adapter
проверяет Class equality, defining loader и CodeSource всех companion classes без
инициализации owner. Отсутствующий или подменённый companion даёт инфраструктурный
отказ. Student/trusted compiled-name collision остаётся запрещённой. ExitCode=7
сам по себе не является исключением.

Private submission_mode берётся из validated descriptor, а student inventory —
из реальных compiled binary names. Adapter сверяет его с classfiles свежего
student root. Только implementation AssertionError с верхним reported student
frame и согласованными resolved Class/loader/CodeSource даёт runtime. Нижние
student frames не повышают trusted assertion; student-tests assertions сохраняют
wrong-answer/mutation семантику. StackTraceElement содержит reported metadata,
а не неподлежащее подделке доказательство источника: произвольный student
setStackTrace не превращается в новый доверенный API. Private bindings и reports
не поступают из upload/feedback; подписи и sandbox остаются обязательными.

Если declared public JUnit test действительно завершился typed runtime/timeout/
output-limit до TestReporter, подписанный adapter добавляет только фиксированное
наблюдение класса сбоя и failed для точного test binding. Текст Throwable и вывод
не копируются. Полученный TestReporter actual сохраняется; для неисполненного
теста actual остаётся неизвестным и статус — not-run.
