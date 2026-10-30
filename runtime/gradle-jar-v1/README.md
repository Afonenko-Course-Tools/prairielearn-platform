# Доверенная сборка production JAR

Новый opt-in `java25-gradle-junit-v1` использует существующий Java runner:
компиляция выбранных исходников → независимый API precheck → фиксированный
`clean jar` установленного Gradle 9.8.0 → прежние trusted JUnit/JavaProcess
проверки. Descriptor содержит закрытый `javaBuild` с `kind: gradle-jar-v1`,
безопасным basename `artifact` и необязательным `mainClass`. Если `mainClass`
отсутствует, собирается обычный library JAR без `Main-Class`; фиктивный main не
нужен. Если поле присутствует, требуется валидное Java binary name: null,
пустая строка и лишние поля отвергаются. В captured project-check это
`java-build` и необязательный `main-class`; omission сохраняется в mapping,
в конфигурации recipe и input digest, без подстановки defaults. Исполняемый
JAR с явно указанным main сохраняет прежний manifest и запуск.

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

Source lock содержит ожидаемые319 JDK/716 Gradle files со статусом `prepared-completion-awaiting-image-admission`. Он не утверждает наличие нового опубликованного образа. В прежнем exact локальном snapshot фактически выполнены finite native сборки; перенос их результата на clean Dockerfile candidate требует отдельного readback и smoke. Исторические published registry/image pins2.2.0 не обновлены.


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

## Версионная подготовка build context

Предпосылки: clean Git checkout, Linux host, Python3.14+ (закрытый zstd reader), gpgv и безопасный owner-controlled cache. Один и тот же preparer используется локально и в CI:

```sh
# Только explicit initial preparation может получать fixed HTTPS inputs.
python3 tools/prepare_native_toolchain.py --fetch
# При готовом cache — повторная аутентификация и materialization без сети:
# python3 tools/prepare_native_toolchain.py --cache /private/exact-cache
python3 tools/prepare_native_toolchain.py --verify-context
python3 tools/prepare_native_toolchain.py --write-build-context /private/fresh-context.tar
# Выполнять только после допуска фактической offline builder boundary:
DOCKER_BUILDKIT=0 docker build --pull=false --network=none --no-cache \
  -f images/java25-grader/Dockerfile -t local/platform-native-toolchain:candidate - < /private/fresh-context.tar
```

Output `.native-toolchain` должен отсутствовать. Cache/outputs не принимают symlink, hardlink, special file, writable parent или collision; partial staging удаляется при отказе. Atomic no-replace публикация не заменяет существующий context. Public input pins/keyring/source inventory находятся в `images/java25-grader/toolchain/`; временный context/cache в Git не входят. Host не запускает installer/Java/Gradle, apt или maintainer scripts. Generated completion authority содержит только package/component provenance, без старых private execution receipts.

Детерминированный TAR передаёт только публичный runtime/runner/normalizer и closed prepared payload. Installer создаёт fresh normalization/completion receipts, проверяет exact source/hardened316 → private319 relation и удаляет distribution ZIP/temporary components. Проверка `--verify-context` повторно выводит hashes из canonical source, поэтому изменение manifest не авторизует изменённый installer/helper. Отсутствие сетевых загрузок при build требует actual builder/resolver admission; flags сами по себе его не доказывают.
