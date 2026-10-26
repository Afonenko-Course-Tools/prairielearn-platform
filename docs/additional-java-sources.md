# Необязательные дополнительные исходники Java

Статус: локальный unreleased candidate поверх Platform2.1.0; published image digest и version не изменены.

Implementation descriptor runtime `java25-junit-v1` может содержать закрытый объект `additionalJavaSources` с обязательными полями `archive`, `maxFiles`, `maxFileBytes`, `maxTotalBytes`, `maxArchiveBytes`. Имя — безопасное basename `.zip`; положительные целые не превышают соответственно128/1048576/4194304/2097152. Основные `sourceFiles` обязательны, ZIP необязателен. Прежний лимит64 относится к основным/test lists; до128 extras имеют отдельный bounded inventory и не теряются на этом лимите. Это транспортные пределы с ручным fallback без score, не ограничения классов или алгоритма.

Архив — обычный файл без symlink, STORED/DEFLATED, до256 записей. Внутри только относительные POSIX `.java` и безопасные directory entries, до32 сегментов/512UTF-8 bytes пути. Абсолютные/drive/backslash/пустые/`.`/`..`/скрытые сегменты, control/NUL, повторные пути, symlink/специальные типы, encryption и file/directory collisions отвергаются. Основные/trusted/private пути нельзя перезаписывать. `a/Helper.java` и `b/Helper.java` сохраняются раздельно. Безопасный каталог может быть общим родителем основных/trusted путей.

Preflight проверяет declared и фактические размеры, CRC, сжатие, UTF-8. BOM передаётся как bytes; языковую допустимость решает javac. Все bounded bytes проверяются до записи извлечённых sources. `extractall`, student commands и обход submission не используются. Проверенные bytes записываются в свежий приватный временный каталог; submission/tests/runtime не перезаписываются. Compiler получает прежний explicit list плюс отсортированный inventory extras при `-sourcepath ''` и `-proc:none`.

Порядок прежний: student compile → независимая API precheck → dependent compile → behavior. Небезопасная/повреждённая/слишком большая доставка: `unsafe-submission`, gradable false, без score, trusted/dependent not-run и сообщение о ручной сдаче. Неверная trusted policy — infrastructure failure; malformed Java — student compilation failure; missing API после successful compile — student-api-mismatch. Без policy старые descriptors не расширяются; fish/mutation policy не принимают.

Результат может содержать `additionalSources`: имя/hash архива и принятый отсортированный inventory `{path,sha256,bytes}`. При unsafe ZIP непроверенный inventory не выдаётся как принятый. ZIP fixtures остаются под `tests/fixtures` и входят в snapshot hashes. Reference extras разрешены только с policy: обязательные filenames сохраняются, дополнительные `.java` доверенный код пакует детерминированно. Generated archive hash имеет ключ `$generated/<archive>` в sourceHashes. Descriptor equality и native delivery hashes остаются обязательными.

PrairieLearn exporter показывает штатный optional upload рядом с редакторами либо в существующей upload-форме. Общий штатный предел PL5MB относится ко всему ответу с редакторными bytes; nominal maxArchiveBytes не обещает этот объём при больших основных файлах. Live PL, Windows и публикация этим локальным контрактом не подтверждены.

## Opt-in необязательных основных файлов

Необязательный boolean `additionalJavaSources.primaryRequired` имеет default `true`.
При `false` `sourceFiles` остаётся непустым starter inventory, а runtime компилирует
только непустую union фактически представленных primary и проверенных ZIP `.java`.
Отсутствующий primary не подставляется. ZIP может содержать его имя; дубликат
присланного primary, trusted/common/generated collision и все прежние unsafe/cap
нарушения отвергаются. Непустой direct ответ допустим без архива. API/tests/scoring
и JDK25 с `--release 25` сохраняются; сбой инструмента не становится оценкой 0.

Авторский ключ `additional-java-sources.primary-required: false` требует полной
bounded policy и штатного upload. Delivery verification проверяет точный набор
optional primary+archive names и отвергает editor. Reference использует реальные
выбранные Java sources, contract — только явно объявленные fixtures. Gradle input
hash связывает фактические primary и ZIP members, без отсутствующего placeholder.

Изменение runner требует нового честного runtime image и обновления registry/lock
по штатному release pipeline. Локальные source tests не подтверждают новый OCI
image; прежний digest не поддерживает новое поле. Версии и pins обновляются только
на отдельном этапе после независимой приёмки.

В opt-in upload отдельно перечисляются только primary без каталогов и архив.
Nested primary передаются внутри ZIP с исходными относительными путями; полный
`sourceFiles` и canonical binding сохраняются. Flattening, кодирование имён и
wildcard загрузка не применяются.
