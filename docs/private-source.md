# Приватный source snapshot

`tools/prepare-private-source.py` принимает clean публичный Git checkout,
выбранный owner и точный grading stage Core. Он сохраняет QMD/config/extensions
публичного commit и заменяет только project partitions из replacementRoots.
Adapter не собирает common файлы, не отбирает teacher материалы и не создаёт ZIP.
Он проверяет Core inventory и hashes, затем создаёт отдельный clean Git snapshot
без remotes. Приватный receipt хранится снаружи snapshot с режимом 0600.

```bash
python3 tools/prepare-private-source.py \
  --source /absolute/public-course --book tasks \
  --materialized /absolute/core-grading-stage \
  --output /absolute/fresh-private-source \
  --receipt /absolute/private-source-receipt.json
python3 tools/build-course.py --source /absolute/fresh-private-source \
  --book tasks --instance example --output /absolute/fresh-native \
  --staging-receipt /absolute/private-source-receipt.json
```

Если export требует полный каталог уже принятой публикации, добавьте к вызову
подготовки один `--publication-catalog /absolute/reference-catalog.json`.
Helper копирует исходные bytes целиком в фиксированный путь
`_site-student/reference-catalog.json` до inventory, private Git commit и receipt.
Путь включается в прежние `receipt.files` и Git tree, даже если `_site-student`
игнорируется Git. Schema и runtime roots не меняются. Происхождение исходного
каталога, точный hash и разрешение на использование связываются внешним typed
receipt; helper не генерирует, не фильтрует и семантически не квалифицирует каталог.
Вход должен быть обычным файлом без symlink/hardlink; изменение во время freeze,
повторный флаг и пересечение target с public Git snapshot означают отказ.
Вызов без флага сохраняет прежнее поведение.

Public origin должен быть credential-free HTTPS. Receipt связывает настоящий
public repository/commit, private stage commit/tree, Core declaration/common/
teacher hashes и полный file inventory. Private commit не приписывается public
origin. Приватный stage и receipt запрещено публиковать в публичном Git/ZIP/site.
Core receipt обязан содержать внутренне полученный sourceCommit, совпадающий
с public HEAD. Config-only commit после материализации требует новой сборки Core;
отсутствующее поле также останавливает freeze до записи.

### Generated seed в отдельном execution checkout

`--source` остаётся чистым публичным checkout. Core receipt может относиться
к другому execution checkout с теми же HTTPS origin, HEAD и полным tracked tree.
`sourceRoot` в исходном receipt не переписывается: это настоящий execution owner.
Helper проверяет оба index, отсутствие skip-worktree/assume-unchanged, каждый
Git blob, живые байты и режимы. Public/common inputs и sourceDocuments сверяются
с обоими источниками. Дополнительные execution-файлы допускаются только как
точные public entries Core внутри выбранных student partitions, включая всю
разрешённую учебную `.git`. Ignored/untracked файлы снаружи, недостающий seed,
ссылки, изменение Core или любого входа во время freeze означают отказ.

Existing recipe читается из чистого checkout и пишет только в execution.
После последнего настоящего materialize --write/--check caller сохраняет
перечисленные runtime outputs capture снаружи execution, не перемещая source
inputs или Core manifest. Этот прежний NativeRun после переноса не предъявляется
как current. Public Git objects копируются только из чистого checkout;
replacement bytes — только из Core. Generated execution не называется clean.
Его status и полный seed inventory до/после freeze сохраняются во внешнем
приватном свидетельстве caller; receipt.publicBase содержит только чистый
repository/commit/book, а materialization.sha256 — исходный Core receipt.

Только под Git roots, уже подтверждёнными generated public entries Core,
допускаются существующие пустые `objects/info`, `objects/pack`, `refs/tags`
с mode0755. Их identity/type/owner/mode/presence и пустота замкнуты до/после
freeze. Произвольный пустой каталог или новый child по-прежнему отказ;
в Core manifest и private-stage эти дополнительные каталоги не добавляются.
Прежний same-root маршрут поддерживает обычный Git worktree с `.git` file;
раздельные P/E остаются самостоятельными checkout.

Host helper из source patch 2.3.1 закрепляется собственными commit и SHA256
во внешнем свидетельстве. Последующий build-course и Context используют
прежнюю принятую assembly 2.3.0 с её двумя authenticated overlays и assets/images.
Нельзя подставлять patched helper checkout вместо builder и приписывать ему
bytes или image provenance 2.3.0. Нового runtime image этот host patch не требует.

Git не индексирует вложенную student/.git. Такие controlled seed файлы остаются
в stage и хешируются receipt вне stage index. Проверка inventory до и после
export отклоняет как изменение, так и добавление seed файла. Отсутствие изменений
в Git status само по себе не считается достаточным доказательством.

Обычный build-course без --staging-receipt сохраняет прежний clean checkout и
HTTPS origin guard. Private-stage режим также требует clean-before/after,
отсутствия remotes и точного receipt. Источник, Core output и stage не пересекаются;
symlink/submodule/special files и неожиданные replacement paths отклоняются.
Созданный snapshot подтверждает состав, а не внешний runtime или Moodle UI.

Receipt резервирует только отсутствующие при freeze runtime roots:
`<book>/_generated`, `<book>/.quarto` и `.quarto`. До export они должны
отсутствовать полностью. После export разрешены только обычные новые файлы
и каталоги в этих roots; каждый hash записывается в runtimeInventory provenance.
Любое добавление снаружи, symlink или изменение исходного/seed файла — отказ.
Для следующего независимого build создайте новый private snapshot: сохранённый
runtime output не становится частью исходного receipt.

Локальные адресные проверки:

```bash
python3 -m unittest discover -s tests -p test_private_source.py
python3 -m unittest discover -s tests -p test_build_course.py
CORE=/absolute/quarto-course EXPORTER=/absolute/quarto-course-prairielearn \
  DOWNLOAD=/absolute/quarto-project-download \
  OLD_PLATFORM=/absolute/clean-published-c020 \
  OLD_RELEASE_ASSETS=/absolute/three-published-v230-assets \
  python3 -m unittest discover -s tests -p test_private_source_native.py
```

Последняя проверка выполняет настоящий Quarto export синтетического курса
из examples/native-course и приватного overlay. Она не запускает External grader
и не доказывает Moodle/native UI integration.

## Внешние архивы через неизменённый runtime builder

Установленный Exporter 8.2.3 принимает явный абсолютный путь manifest через
`PRAIRIELEARN_PUBLICATION_CONDITIONS`. Неизменённый build-course.py из принятой
assembly 2.3.0 наследует это окружение настоящему Quarto subprocess; нового
builder flag или выпуска Platform 2.3.3 для передачи пути нет. Helper 2.3.2
остаётся отдельным source-only инструментом заморозки.

```bash
PRAIRIELEARN_PUBLICATION_CONDITIONS=/absolute/publication-conditions.json \
  python3 /absolute/accepted-c020-assembly/tools/build-course.py \
  --source /absolute/fresh-private-source --book tasks --instance pilot \
  --output /absolute/fresh-native \
  --staging-receipt /absolute/private-source-receipt.json \
  --runtime-registry /absolute/accepted-assets/published-runtime-profiles.json
```

Исполнитель закрепляет exact ENV и typed refs manifest/исторической публикации/
всех whole ZIP до/после операции. Exporter отказывает при CLI+ENV одновременно,
проверяет current publicBase, source/ZIP bytes и сохраняет JSON dependency receipt
в stdout. Обычные ZIP/link inventories и delivery hash связывают output. При
отсутствии обоих inputs прежний маршрут сохраняется. Runtime assembly проверяет
прежний c020 source/tree/tag/VERSION, два data overlays и четыре внешних assets;
нового code overlay, подмены provenance или runtime image release нет.

Hosted native integration отдельно проверяет настоящий неизменённый c020 CLI,
опубликованные asset hashes и Context admission, private-stage publicBase,
whole ZIP/link и stdout receipt через ENV. Первая UNIT-registry поставка этого
synthetic теста — отдельный baseline; она не доказывает production assembly.
