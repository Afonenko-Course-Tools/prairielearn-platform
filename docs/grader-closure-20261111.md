# Диагностика grader и стоимость Gradle: 11 ноября 2026

Локальный кандидат для Platform #31/#34 использует настоящий Temurin25.0.5+8
и Gradle9.8.2. База исходников — `d7a0b0d`; текущая дельта сохранена в рабочем
дереве. Java-only candidate —
`sha256:dec50af3f26e688a20679f08448991653f60cbedb1d4698af420a078980e32d4`.
Он собран без сети поверх принятого локального image
`sha256:b963e4ef1abce2a40c2a9c00b5e548814c3c7be074b24a34c869edc1adcf1282`
с текущими `runtime`, `runtime-profiles.json`, `grade.py` и компиляцией public
adapter. Полный обычный Dockerfile содержит ту же компиляцию; локальный
производный candidate не является доказательством hosted build/push/pull.

## Первичные отказы #34

Исходные14 `JUnitJob` contracts на фактическом JDK25 проходили. Исторические
красные проверки PR32 этим не воспроизведены: старые missing-report cases
проверяли только наличие исключения. Host с JDK27 не подходит для такой
проверки; явный preflight правильно его отклоняет.

Точные текущие контрпримеры:

- `System.exit(23)` после записи stdout/stderr: обе компиляции завершились,
  отчёта нет; прежний `GraderError` терял код и потоки.
- Зацикливание после записи stdout: timeout возвращал ungradable результат,
  но удалял stdout, exit и durations.
- Повреждённый отчёт: ошибка decoder после успешного execution теряла
  completed phases. Независимый counterexample подставляет отказ reader.
- Docker exit125 и `TimeoutExpired` теряли первичные stdout/exit/streams
  после преобразования ошибки в результат `GradingJob`.

Теперь существующая строковая `diagnostics` содержит `stage`,
`<stage>.exitCode`, `<stage>.termination`, `<stage>.stdout`, `<stage>.stderr`.
Суммарный размер двух потоков ограничен `max-output-bytes`, в том числе при
неверном UTF-8. Причины `exit`, `signal`, `timeout`, `output_limit`,
`interrupted`, `spawn-error` различаются. При внешнем timeout кода завершения
Docker нет, и он не выдумывается. Прерывание оператора сохраняет исходный
`KeyboardInterrupt`; process group останавливается прежним supervisor.

Контекст фаз несёт сам `GraderError`; CLI, host `GradingJob` и native catch
сохраняют его до private verification result. Уже завершённые компиляции
остаются `success`. Повреждённые/неполные отчёты и trusted tool exceptions
не получают score. Проверки компиляции студента, API mismatch, штатного
assertion с именем/expected/actual и исключения студента сохраняют прежние
разные классификации. Student boundary скрывает private tool diagnostics и
полный teacher trace. Публичный Launcher/Listener/OpenTest4J adapter сохраняет
принятый договор; исторический named-module observer не возвращался.

## Измерения #31

Каждый сравнительный job — отдельный контейнер без сети, CPU0.9, RAM512MiB,
pids128, свежие HOME/user-cache/project-cache/sources/output/JAR. Использованы
неизменённые `reference`, `checks`, `observations`, `api` файлов действующего
курса Java. Встроенный recipe собирает production sources; присланные build
scripts не запускаются. Лимиты compile15s/run10s не увеличивались.

| Задание | Исходники / cases | Gradle до, с | Gradle после, с | Полный job до, с | Полный job после, с |
| --- | --- | --- | --- | --- | --- |
| `files/byte-file-copy` | 2 / 7 | 8.586 / 8.586 | 5.510 / 5.443 | 12.417 / 12.333 | 8.722 / 8.498 |
| `projects/airline-persistence-project` | 6 / 4 | 9.009 / 9.691 | 6.352 / 6.155 | 12.922 / 13.492 | 9.906 / 9.144 |

Обе колонки содержат cold и второй свежий job, без межпопыточного кеша.
Все8 сравнительных jobs получили score1 и полный набор JUnit cases.
Эти измерения двух задач не доказывают ускорение полного курса; машина
использовалась и другими работами. Отдельная инструментированная серия под
поздней нагрузкой заняла больше времени и использована только для счётчиков.

Разложение на минимальном обычном проекте того же образа:

| Компонент | До | После |
| --- | --- | --- |
| отдельный `gradle --version` | 0.951 / 0.863s | 0.443 / 0.396s с tier1; grading job его не запускает |
| cold `jar`, client+build tier1 | 10.610 / 9.804s | 4.551 / 4.545s |
| `--profile`, совместимые client JVM args | — | startup1.650s; settings0.530s; project config0.686s; compileJava1.448s; jar0.076s |
| adapter compilation, byte-copy | 0.723 / 0.768s | 0 / 0s: `.class` из immutable image |

Основная подтверждённая правка — tier1 для короткоживущих Gradle JVM.
Совпадающие client/build JVM args (`Xms64m`, `Xmx128m`, ActiveProcessorCount2,
UsePerfData off, tier1) устраняют single-use build daemon, что подтверждено
настоящим `--info`. Штатный compiler worker Gradle остаётся; он использует
публичный JDK compiler API. Download зависимостей нет, JUnit JAR уже в image,
recipe/configuration остаются обычными Gradle. Общий writable build cache или
повторное использование студенческих classes не добавлялись.

Read-only supervisor profiling фактических jobs дал:

| Задание | Вызовы `_run` | Python `Popen` | `Path.rglob` |
| --- | --- | --- | --- |
| byte-copy | 16 | 26 | 22 |
| airline | 20 | 30 | 22 |

`Popen` включает короткие DAC/UID probes и root supervisor проверки; Java
дочерние процессы внутри JVM в этот счётчик не входят. `--info` отдельно
показывает один compiler worker и отсутствие build daemon. Разница4 `_run`
между заданиями соответствует4 дополнительным trusted source readability
probes.22 обхода относятся к classpath/namespace/collision проверкам,
копированию native output и immutable adapter; число исходников не вызывает
повторного полного обхода курса. Эти защитные проверки сохранены.

## Проверка и оставшаяся граница

- Новые7 diagnostic contracts включают real subprocess streams/exit/signal,
  bounded invalid UTF-8, operator interruption, JUnit missing-report/timeout
  и отказ decoder. Первоначальные6 cases давали7 ошибок на исходном grader;
  текущие проверки проходят на JDK25.
- 10 фактических сценариев frozen image: plain и native incomplete report,
  timeout, tool failure; native cold/repeat success, assertion и student
  exception. Неполный report не получает score; completed phases сохранены.
- Существующие image/API containment проверки:6 PASS,1 SKIP из-за отсутствия
  необязательного `JAVA_CONSOLE_SUPPORT`; native temporary files/entropy,
  worker feedback и API mismatch matrix проверены реальными контейнерами.
- Адресная source группа:63 PASS,17 SKIP,1 отказ из-за отсутствующего fish
  внутри Java-only image. Тот же fish boundary отдельно прошёл на host с
  установленным fish. Это ограничение среды явно отделено от Java результата.
- После дополнения outer diagnostics:13 process/cancellation controls PASS;
  строгий Pyright изменённых Python файлов —0 errors.2 предупреждения о
  source системного `jsonschema` не вызваны этой дельтой.
-7 реальных synthetic exporter packets editor v1/v2: correct1, assertion0,
  compilation0; прежние2 файла приняты под новой формой с3 primary paths при
  `primaryRequired:false`. Существующие исходники заданий не менялись.

Команды, JSON результатов, Gradle `--info`/`--profile`, контрпримеры,
производный Dockerfile и ID находятся в `/tmp/close-grader`. Приёмка полного
актуального declared/delivery набора, независимая рецензия и hosted Java-only
публикация выполняются координатором отдельно; исторический census не
подменяет эти проверки.
