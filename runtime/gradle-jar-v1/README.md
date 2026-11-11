# Обычная сборка Java с Gradle

Профиль `java25-gradle-junit-v1` использует штатный Java plugin Gradle: выбранные
production sources компилируются с `--release 25`, `UTF-8` и `-proc:none` один раз.
Этот output идёт одновременно в обычную задачу `jar` и в приватную API/JUnit
проверку. Собственные source/JAR/JDK/Gradle inventories и toolchain lock удалены.

Recipe поддерживает обычные `jar`, `run`, `test`. Production sources находятся
в `src`, тесты обычного Gradle-проекта — в `tests`. `test` использует
`useJUnitPlatform()` и JUnit JAR из образа; для локальной проверки путь можно
передать через `-PjunitJar=/absolute/path/to/junit.jar`. Задачи компиляции и
тестирования включены. Gradle сам управляет зависимостями задач и повторным
использованием production output в пределах сборки.

`native-config.json` содержит `artifact` и необязательный `mainClass` из
проверенного descriptor `javaBuild`. Без `mainClass` получается библиотечный JAR;
при его наличии работают manifest `Main-Class` и обычный `run`. Поданные
студентом build scripts, Wrapper и init scripts не исполняются. Учебные cases,
веса и требования к JAR задаются прежними trusted тестами.

## Поставка и границы исполнения

Образ собирается обычным Dockerfile из публичных JDK/Gradle images и исходников
runtime. Предварительная `.native-toolchain` и ручной normalizer не требуются:

```sh
docker build -f images/java25-grader/Dockerfile -t local/java25-grader .
PL_TEST_IMAGE=local/java25-grader python3 -m unittest discover -s tests -p test_plain_image.py -v
```

Build role `nativebuild` получает полный JDK в `/opt/native-jdk`, свежие выбранные
sources и встроенный recipe. У этой роли нет доступа к private trusted tests и
job descriptor. Проверка `sbuser` использует JDK25 без management JNI libraries,
а DAC запрещает ей доступ к полному build JDK. Supervisor проверяет реальные UID,
группы, отсутствие сетевых интерфейсов кроме loopback и доступ к приватным
файлам. После Gradle он завершает build-role процессы и удаляет temporary
work/HOME/cache перед private API/JUnit фазой. Эти проверки прав и процессов
не подменяются content hashes.

`buildEvidence` содержит status, путь/размер JAR и фактическую длительность.
Compiler errors студента дают student-compilation-failure. Ошибка Gradle вне
компиляции студента или нарушение границы исполнения — infrastructure failure
без score. Private `gradle.log` сохраняется для оператора; публичная обратная
связь фильтруется прежним `student_result`.

## Отчёт JUnit

Небольшой адаптер публичных Launcher/Listener API сохраняет отдельные JUnit
cases, их имена, статусы и диагностику OpenTest4J. Python decoder проверяет
полноту зарегистрированных/начатых/завершённых cases до вычисления оценки.
Действующий договор — [простой запуск Java/JUnit](../../docs/public-junit.md).
Незавершённый или повреждённый отчёт означает инфраструктурный сбой без score.

В private verification report поле `diagnostics.stage` указывает последний
процесс, а `<stage>.exitCode`, `<stage>.termination`, `<stage>.stdout` и
`<stage>.stderr` сохраняют первичную диагностику. Потоки ограничены общим
`max-output-bytes`; `output` остаётся совместимым объединённым выводом.
Timeout, signal, operator interruption и отсутствие executable различаются.
Уже завершённые `studentCompilation`/`trustedCompilation` не превращаются
в `not-run` при последующем отказе JUnit. Native student feedback по-прежнему
скрывает private диагностику, teacher trace и исходники trusted checks.

## Накладные расходы

Gradle client и build JVM используют одинаковые `-Xms64m -Xmx128m`,
`-XX:ActiveProcessorCount=2`, `-XX:-UsePerfData`, `-XX:TieredStopAtLevel=1`.
Это позволяет обычному `--no-daemon` выполнить сборку в текущем процессе;
JDK compiler worker, если его выбирает Gradle, остаётся штатным процессом.
Разделённые seed-файлы сохраняют быстрый доступ к энтропии внутри Landlock.
Предварительных `gradle --version` и `clean` в grading job нет. Проект,
HOME, user-cache, project-cache, classes и JAR остаются свежими в каждой попытке.
Student build scripts не копируются в проект и не исполняются.

Dockerfile заранее компилирует неизменный public adapter и API support из
исходников того же image с `--release 25`. Grader копирует эти `.class` в
прежний приватный каталог текущего job; каталоги и библиотеки получают
прежние read-only права. Код студента никогда не входит в этот набор. Host
без image по-прежнему компилирует adapter отдельно для каждого job.

Сравнительные измерения и границы проверки описаны в
[отчёте #31/#34](../../docs/grader-closure-20261111.md). Локальный image
не подтверждает hosted публикацию или полноту проверки всех задач курса.
