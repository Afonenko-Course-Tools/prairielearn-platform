# Запуск полного native exporter

`tools/build-course.py` вызывает единственный установленный
`entrypoints/export-course.ts` выбранного owner из одного из двух namespace:
`_extensions/course-prairielearn` либо
`_extensions/Afonenko-Course-Tools/course-prairielearn`.
В Quarto передаётся абсолютный путь entrypoint; cwd — `source/book`, аргумент
source остаётся корнем рабочего каталога. Второго exporter и QMD resolver нет.
Чистый Git status и отдельный staging receipt для текущего вызова не требуются.

```sh
python3 -B tools/build-course.py \
  --source /absolute/course --book tasks --instance 2026-2027-s1 \
  --output /private/build/native-course \
  --runtime-registry /private/runtime-profiles.json
python3 -B tools/check-course.py verify \
  --manifest /private/build/native-course-checks.json \
  --scope delivery --delivery /private/build/native-course/delivery.json \
  --backend container --output /private/build/check-report.json
```

Native delivery v5 содержит выбранные пути и UUID. Приватный checks v3 содержит
реальные выбранные bytes проверок. Он хранится вне native-каталога; его нельзя
подменять списком source paths или включать в student-site. Проверка package
integrity, UUID и ссылок assessment выполняется до конечной публикации.
Полный declared/delivery контроль grader вызывается отдельно; child exit0 сам
по себе не означает корректный пакет или успешное оценивание.

## Выходы и временный каталог

Source и parent output должны быть реальными каталогами без path aliases.
Output создаётся заново вне source. Builder выделяет закрытый `.pl-export-*`
рядом с output; exporter получает `<stage>/native` и `<stage>/checks.json`.
Для адресного запуска можно заранее выбрать отсутствующий абсолютный
нормализованный sibling через `--export-stage /private/build/fresh-stage`.
Создаёт и удаляет этот каталог сам builder; существующий каталог не используется.
Stage не является receipt, authority или входом повторного экспорта.

После проверки builder создаёт `<output>-checks.json` исключительно, с mode0600,
и публикует каталог через Linux `renameat2(RENAME_NOREPLACE)`. Существующий output,
включая пустой каталог конкурента, сохраняется. При ошибке записи либо коллизии
публикации builder удаляет собственный checks и stage, сохраняя первичную ошибку;
чужой checks, занявший путь, не удаляется. После исправления причины вызов можно
повторить с новым отсутствующим output. Ошибка самого удаления может оставить
собственный временный путь для ручной очистки.

## Разработка и доставка

Для loopback preview используйте [Local prepare/up](development.md), сохраняющий
стабильный writable course path и native numeric identity. Production-доставка
готового Git export через штатный REST sync показана в
[примере Ansible](../examples/course-cd/README.md); доступ и целевой environment
задаются оператором отдельно. Ни build, ни verify не переносят старые оценки,
не создают Moodle registration и не доказывают прохождение браузерного сценария.

[Прежнее описание 2.5.2](history/qualified-launch-2.5.2.md) сохранено для истории.
Его private-source/assembly receipts, parent flock и fd-relative cleanup не
являются API текущего builder.
