# Доверенная сборка production JAR

Новый opt-in `java25-gradle-junit-v1` использует существующий Java runner:
компиляция выбранных исходников → независимый API precheck → фиксированный
`clean jar` установленного Gradle 9.8.0 → прежние trusted JUnit/JavaProcess
проверки. Descriptor содержит закрытый `javaBuild` с `kind: gradle-jar-v1`,
`mainClass` и безопасным basename `artifact`. В captured project-check это
`java-build` и `main-class`; остальные поля имеют тот же смысл.

Сборка использует только копии выбранных production Java sources, этот recipe,
settings и проверенные значения descriptor. Присланные build scripts, Wrapper,
init scripts, tests и внешние production dependencies не запускаются. Проверка
не оценивает учебную часть написания студентом Gradle scripts.

Требуются официальный изолированный supervisor, отдельный проверенный UID,
реальное отсутствие сети, недоступность private inputs и полный допущенный
installation inventory Gradle/JDK. Новый profile в host diagnostic отказывает
после успешных javac/API стадий. Сбой trusted build или integrity даёт
`infrastructure-failure`, `gradable: false`, без score.

Результат сборки принимается как свежий regular single-link JAR; supervisor
создаёт защищённый `build/libs/<artifact>` текущего job. Его hash, inode,
владелец, права и parents проверяются до и после dependent execution.
Private `buildEvidence` связывает selected source bytes, recipe/toolchain
closure и artifact. Public student feedback это поле не содержит.
`check-course` сохраняет operator logs/manifest рядом с private report в
`<report>.private-build-evidence/` до cleanup scratch.

Текущий lock подтверждает официальный distribution archive и 716 regular files.
Полный JDK/base-image admission остаётся открытым: status
`prepared-archive-awaiting-image-admission` намеренно не допускает исполнение.
Исторические published registry/image pins не обновлены. Новый image,
изолированная offline сборка, exact tuple/export/receipt, CI и публикация
требуют отдельных фактических доказательств. Синтетические fixtures unit tests
не являются OCI image или доказательством настоящего Gradle execution.


## Отдельные роли build и grading

`nativebuild` — фиксированная non-login учётная запись с собственной private group.
Оператор записывает фактически выделенные UID/GID. Только trusted builtin Gradle recipe
получает полный JDK319 в `/opt/native-jdk`: root-owned дерево, корень0750 и GID
группы `nativebuild`. Выбранные production Java sources компилируются без processors;
пользовательские build scripts, тесты и bindings не являются build inputs.

`sbuser` выполняет API/JUnit и обычные/вложенные student JVM на неизменённом hardened
JDK316 `/usr/lib/jvm/java-25-openjdk-amd64`. Абсолютные `java`/compiler commands и чистое
окружение не наследуют build PATH, JAVA_HOME, options, HOME/cache или library paths.
DAC запрещает grading UID читать, копировать, исполнять и `System.load` компоненты
полного build JDK. Указание JAVA_HOME само по себе не считается защитой.

Три JNI-компонента берутся только из подписанного same-build Ubuntu package
`openjdk-25-jre-headless:amd64` версии `25.0.4+7-1~24.04`,58945368B,
SHA256 `6c964acad9b3c929edb97eba9acc799907a68c89011336e813c88ee26fb00e9c`.
Проверяются signed metadata, control identity,94 совпадающих regular JRE members,
точные три payload hash/mode/bytes и ELF dependencies. Исходный normalizer receipt316
не переписывается; отдельный completion receipt связывает hardened316 и полный319.

Перед private фазой supervisor завершает и reap-ит build-role descendants в своём
container PID namespace, проверяет отсутствие оставшихся процессов и удаляет свежие
build work/HOME/cache. До и после grading повторно проверяются роли, группы,
приватный корень, core hardened payload и отказ доступа к полному JDK. Drift —
infrastructure/noScore, а не ошибка студента. Exact null helper81cd… не изменён.

Dockerfile требует закрытые `.native-toolchain` inputs, подготовленные оператором;
он не выполняет apt, загрузки или package maintainer scripts. Source expected lock
со статусом `prepared-completion-awaiting-image-admission` — описание ожидаемых319
файлов, не доказательство установки. Generated private baked view/installed lock
принимаются только после actual preparation/readback и finite kernel/native gates.
Исторические published registry/image pins не объявляются новым native candidate.
