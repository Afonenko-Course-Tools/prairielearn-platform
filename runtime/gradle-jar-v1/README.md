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
