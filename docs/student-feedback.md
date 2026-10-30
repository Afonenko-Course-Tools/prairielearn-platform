# Результат внешней проверки

Штатный grader entrypoint записывает в native `results/results.json` безопасную студенческую проекцию. Один модуль `runtime/student_feedback.py` обслуживает Java и fish. Его hash входит в `sharedFiles` каждого runtime и в private dependency closure.

Java implementation возвращает полный набор фактически завершённых оценочных случаев: русское имя из доверенного `@DisplayName` или имени dynamic/parameterized случая, статус и наблюдённые предметные expected/actual. Каждый случай имеет одинаковый вес; при `weighted` оценка равна passed/total независимо от старых upstream points tags. Контейнеры, методы-фабрики и API precheck не увеличивают знаменатель. Demo не заменяет оценочный набор.

RESULTS содержит русские reason, observed и whatCheck для классов compile/runtime/timeout/wrong-answer/infrastructure. Достоверная собственная некомпиляция или API mismatch — оцениваемый ноль текущей попытки; зависимые тесты не запускались, поэтому фиктивных тестовых исходов нет. Компиляторная диагностика показывает имя собственного Java-файла, строку и категорию ошибки по-русски без исходного текста и внутренних путей. Успешный API precheck сохраняется в приватном отчёте и не занимает место в студенческой панели.

Stdout/stderr, stack traces, произвольные Throwable messages, эталоны и служебные сведения остаются приватными. Сбой проверяющей среды не имеет score и помечается grading_error. Наличие файла не создаёт автоматический успех. Fish и student-tests сохраняют собственную текущую проекцию.

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

Это часть существующего project-check, а не новый DSL/runner. `public-cases` — allowlist: уникальные id, короткое явное name (что проверяется), exact test binding, input/state/action и expected. Пустая строка допустима как явный опубликованный вход/результат. Для fish эти явно опубликованные случаи получают actual/status в native tests panel. Java дополнительно показывает весь достоверно завершённый оценочный набор. Без фактического observation статус not-run, actual=null; успешный результат не придумывается.

JUnit использует штатный `TestReporter.publishEntry(Map.of("public-case", "normal", "actual", actual))`. Native adapter связывает entry с реальным `Class#method` и исходом этого же теста. Entries другого метода/закрытого ID не публикуются. Для существующего fish checker необязательный третий элемент `(name, passed, observedText)` даёт наблюдение; exact binding — `caseIndex: name`. Прежние пары `(name, passed)` сохраняют закрытую семантику. Assertion messages не используются как публичное объяснение. Для Java expected/actual передаются только как фактические предметные наблюдения доверенного теста через `TestReporter.publishEntry(Map.of("expected", expected, "actual", actual))`. Поля `AssertionFailedError` не публикуются: студент может создать такое исключение и заменить его stack trace; класс исключения и trace не доказывают происхождение значений. `toString()` произвольных объектов, исключений и эталонов не вызывается. Обычный `assertEquals` без явного наблюдения сохраняет имя, статус и долю баллов; отсутствующие expected/actual остаются неизвестными (поля отсутствуют, native panel пишет «не установлено»). Это открытая граница полного feedback по решению 37: текущий listener не наблюдает аргументы штатного assertion до выполнения студенческого кода. Для доступного сейчас наблюдения автор вычисляет actual один раз, публикует предметные строки через тот же TestReporter и затем сравнивает те же значения штатным assertion; второго описания теста в YAML не требуется. Автоматическое получение значений обычных assertions требует отдельного проверяемого trusted observation в месте вызова; перенос полей Throwable обратно эту задачу не решает. Эти строки и display names предназначены студенту, поэтому автор не помещает в них секреты или служебные canaries. Отдельного списка обязательных публичных demo для полного набора не требуется.

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

## Полнота результата JUnit

Адаптер сохраняет terminal marker плана, зарегистрированные и начатые unique IDs,
каждый исход и класс отказа. Потребитель отклоняет повторные JSON keys/IDs,
несогласованные счётчики, потерянные исходы, незавершённый план и повреждённый
отчёт. Skipped/aborted случаи, сбой контейнера и обрыв всего executor не дают
частичную оценку. Typed timeout отдельной вложенной программы считается failed
для этого фактически завершённого случая и сохраняет баллы остальных случаев.
Сбой или incomplete результат должен сохранять прежний best/manual на native
границе; локальный runner не подтверждает это поведение живого Gateway.

Оценка runner остаётся долей от 0 до 1. Соотношение 80/20 задаётся native
assessment через autoPoints/manualPoints; runner не умножает долю на 0.8.

Исходный кандидат C3-1 добавляет [наблюдения настоящих JUnit assertions](junit-assertion-feedback.md) внутри тех же leaves и signed counts. Это отдельный source protocol2; прежний OCI image и полный census не получают автоматического PASS.
