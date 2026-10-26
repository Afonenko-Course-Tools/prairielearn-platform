# Проверка delivery v3

Delivery v3 явно закрепляет `grading.method` (`external`, `mixed`, `manual`), нормализованный `submission`, UUID и публичный project root каждого вопроса. У external/mixed дополнительно обязательны runtime, project-check и точный состав источников. Читатели bootstrap, bridge и Gateway отвергают delivery v2; публичный per-slot-results-v2 сохраняется.

`check-course verify --scope delivery` проверяет весь фактический native пакет: pinned upstream JSON schemas, SHA файлов, assessment/slot/instance bindings, upload/editor controls, manual no-grader и внешние дескрипторы. `verification-receipt.json` для staging — закрытый envelope v3 с package proof для всех вопросов. Automatic proof внутри остаётся прежней строгой v1: непустое исполнение ровно external/mixed, полный обязательный набор сценариев, container evidence, image и dependency closure. Wholly manual имеет `automatic.state: not-applicable` с причиной `all-questions-manual`; jobs/results/score для него не создаются. Пустой `verify_results([])` по-прежнему запрещён.

Host и выбранные `--id`/`--scenario` остаются диагностикой. Они не заменяют staging proof. Local candidate images не допускаются к production staging; обычные source, clean, HTTPS и private-stage receipt guards сохранены.

`selection: choice` создаёт отдельную native zone `bestQuestions: 1` со всеми видимыми вопросами. Bridge проверяет каждый candidate row, текущую попытку, полную привязку group/zone и manual pending до выбора одного представителя. Полная принятая альтернатива имеет приоритет; далее score и стабильный lexical ID. Две частичные оценки не складываются, две полные не удваивают вес. Gateway закрепляет canonical choice pool, поэтому лучший представитель может смениться в той же попытке; fixed/random сохраняют выбранный ID. Pending teacher выбранного представителя не создаёт новый FullyGraded AGS event и не переписывает прежнюю очередь оценок.

Package proof не является оценкой ручной работы и не закрывает student/teacher UI, Mixed/choice UI, actual External pipeline или Moodle authentication. Эти наблюдения выполняются отдельно на точном артефакте.

Завершённый частичный winner сохраняет свои score/points/status даже при pending loser: FullyGraded означает завершённую оценку представителя, а не максимальный балл или принятую лабораторную. Pending winner блокирует новый event. Ranking остаётся full → score → lexical ID; pending-first и подмена status от loser запрещены.

Upload control проверяется по фактическим атрибутам native элемента:
для automatic/mixed обязательные file-names точно совпадают с canonical sources,
а optional-file-names — только с объявленным additionalJavaSources.archive.
Пустые, повторные, посторонние и выходящие из проекта имена запрещены. Manual
принимает штатные именованные файлы и pattern upload без создания auto proof.

При `additionalJavaSources.primaryRequired: false` допускается только upload:
`file-names` пуст, `optional-file-names` в точности содержит bound primary names и
объявленный ZIP archive. Отсутствие поля/`true` сохраняет прежние проверки.

В opt-in upload отдельно перечисляются только primary без каталогов и архив.
Nested primary передаются внутри ZIP с исходными относительными путями; полный
`sourceFiles` и canonical binding сохраняются. Flattening, кодирование имён и
wildcard загрузка не применяются.
