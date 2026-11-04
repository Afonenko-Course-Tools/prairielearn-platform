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

Штатный `LegacyXmlReportGeneratingListener` JUnit производит XML; Python reader
вычисляет статусы и долю из этих отчётов. Listener в существующем закрытом Java module сохраняет полезные
assertion checks, public observations, объявленные JUnit points и происхождение
исключения. Он проверяет фактический CodeSource student/console classes.
JSON не задаёт счётчики или оценку: его закрытый event ledger используется для
проверки аутентичности XML. Одноразовый ключ текущего запуска подписывает feedback;
доступ student reflection к private listener state закрыт Java module, Unsafe
memory access запрещён. Source/toolchain/artifact inventories для этого не нужны.
Повреждённый или
незавершённый отчёт не становится нулём студента.

Локально проверены настоящий Gradle `jar/run/test` и JDK25. Новый Docker image
не собран и не опубликован в этой сессии; наличие Dockerfile и указанных tags
не подтверждает OCI/runtime квалификацию. Исторические image digests сохранены.
