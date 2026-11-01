# Подготовленная граница native запуска

`build-course.py` 2.5.2 сохраняет существующие Git/origin, package_integrity,
provenance, private-source/assembly/currentness и atomic no-replace проверки.
Единственный установленный `entrypoints/export-course.ts` выбирается из прежних
двух namespace; аргумент становится абсолютным, а cwd — фактическим owner
`source/book`. Аргумент C source остаётся корнем Git repository. Это техническая
граница существующего C nativeEntry, без второго exporter или QMD resolver.

## Свежий stage

Необязательный `--export-stage` — абсолютный нормализованный путь нового
соседнего каталога output. Его выбирают **до** R/M/E и независимого prior P,
а создаёт сам builder **после** разрешённого запуска, эксклюзивно с mode0700.
Известны точные будущие C arguments `<stage>/native` и `<stage>/checks.json`.
Stage не является immutable K, authority, permission token или reusable receipt.

```sh
# Только после qualified Root preflight, source/runtime freeze и independent P.
# Для согласованного Java author-capture route; SP environment проверяется отдельно.
export COURSE_SITE_DEFER_DOWNLOADS=1
python3 -B /absolute/published-platform/tools/build-course.py \
  --source /absolute/clean-course --book tasks --instance 2026-2027-s1 \
  --output /private/build-epoch/native-course \
  --export-stage /private/build-epoch/export-stage \
  --runtime-registry /private/platform-assets/published-runtime-profiles.json
```

Parent stage/output должен существовать и иметь canonical physical path.
Existing stage любого вида, alias/dot-dot, другой parent и пересечение с
source/output/private-checks/registry/private receipt отвергаются до C.
Непересечение с другими owners, capsule и остальными immutable inputs остаётся
обязательной частью внешней Root qualification: builder не получает их модель
и не вводит новый resolver окружения. Published provider preflight выполняется
до operator L; exact L затем входит в прежние S/G/K и P.

Без опции builder использует прежний случайный `.pl-full-export-*` stage.
Оба варианта проходят один общий хвост проверки/публикации. Непустой native
payload и checks нельзя заменить child exit0; manual/Internal/Workspace не
получают фиктивные code Jobs. Полный inventory/container verify и настоящий
успешный delivery-verification receipt остаются обязательными после P.

## Владение и cleanup

Builder удерживает parent/stage directory FDs и nonblocking exclusive flock
на parent до окончания cleanup. Второй builder того же parent отказывает,
а не ждёт и не повторяет export. Удерживаются identities native/checks и
созданного private checks output; parent/stage/product замены отвергаются
перед consume/publication. Публикация использует fd-relative
`renameat2(RENAME_NOREPLACE)` и сохраняет даже существующий пустой output.

Перед каждым перечислением cleanup открывает свежий directory stream через
`os.open('.', dir_fd=held_fd)`, проверяет тот же inode и закрывает reader.
Это учитывает entries, добавленные после открытия пустого stage, не меняя
владение и не разрешая исходный путь заново.
Cleanup рекурсивно адресует только удержанный stage FD; symlinks не
обходятся. Он не делает `stat(path)` → `rmtree(path)` с повторным
разрешением имени. При обнаруженной смене parent/stage он отказывает;
если замена обнаружена во время cleanup, работа могла затронуть только
ранее удержанный собственный каталог, а не replacement по старому имени.
Условие protected parent и exclusive writer действует до завершения
cleanup: mode0700/flock не обещают защиту против произвольного hostile
same-UID процесса, игнорирующего эту эксплуатационную предпосылку.

Исходная ошибка C/валидации/отмены сохраняется; отказ cleanup добавляется
как note. CLI печатает эти notes. После native rename опубликованный output
и его private checks сохраняются даже при последующем исключении. Сообщение
содержит фактический outcome и оставшийся stage для ручного восстановления.
Нельзя автоматически повторять C, переиспользовать stage или создавать
новый успешный receipt на основании частичного результата.

## Границы выпуска

Локальные inert-spy/package unit tests не исполняют C и не доказывают prior P,
actual course/full135, Moodle или production qualification. Для 2.5.2 нужны
DIFFERENT technical review, настоящий hosted CI, четыре новых OCI с source
revision и три новых authenticated assets с readback/pins. Старые 2.5.1
source/tags/receipts неизменны. Публичные runtime/schema/grade contracts не
меняются этой launch правкой.
