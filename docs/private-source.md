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

Public origin должен быть credential-free HTTPS. Receipt связывает настоящий
public repository/commit, private stage commit/tree, Core declaration/common/
teacher hashes и полный file inventory. Private commit не приписывается public
origin. Приватный stage и receipt запрещено публиковать в публичном Git/ZIP/site.
Core receipt обязан содержать внутренне полученный sourceCommit, совпадающий
с public HEAD. Config-only commit после материализации требует новой сборки Core;
отсутствующее поле также останавливает freeze до записи.

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
  python3 -m unittest discover -s tests -p test_private_source_native.py
```

Последняя проверка выполняет настоящий Quarto export синтетического курса
из examples/native-course и приватного overlay. Она не запускает External grader
и не доказывает Moodle/native UI integration.
