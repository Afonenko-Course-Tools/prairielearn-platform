# Community 2.5.3 без замены grader и Workspace

Это отдельный выпуск Community с принятым recognized-credit/private-code Source
`83c4dd433090b094d05c1e0e555156992c636852`. Поправка publisher меняет только VERSION,
workflow, его Source-проверки и эту инструкцию. Dockerfile, pinned upstream,
все его COPY inputs, grader/Workspace/runtime/schema/package inputs сохраняются.
Существующий `publish-runtime.yml` получает выбор `components: all | community`;
по умолчанию остаётся полный режим `all` с обязательным точным Exporter commit.

## Проверяемая публикация

После независимой проверки и CI интегрировать Source PR. Сверить tree принятого
Source с actual merge commit. Команда ROOT для точного интегрированного HEAD:

```
gh workflow run publish-runtime.yml \
  --repo Afonenko-Course-Tools/prairielearn-platform --ref main \
  -f version=2.5.3 -f reviewed_commit=<EXACT_MERGED_HEAD> -f components=community
```

Ветка Community проверяет exact main/source/VERSION, исполняет Bridge и все
recognized Source-тесты (aggregate — на настоящем pinned dist после настоящей
patch-функции), проверяет отсутствие своего registry tag, собирает прежний
Dockerfile, проверяет Node syntax, публикует только Community и повторно
загружает точный digest. Readback требует правильные registry/repository и OCI
revision/source labels. Публикационный artifact
`platform-community-digest-2.5.3` содержит `community-image.txt` и
`community-image-inspect.json`. Действительный digest появляется только после
завершения workflow; локальный image ID `ca6d…` его не заменяет.

ROOT создаёт новый numbered tag/draft release `v2.5.3` на проверенном merge HEAD,
прикладывает эти два readback-файла и публикует после проверки результата.
При уже существующем release/tag/image сначала установить его точное состояние;
ни tag, ни image не перезаписывать. Ошибка или неизвестный исход не означает
разрешения повторно push того же immutable tag.

Этот режим не создаёт семейный253 `runtime-image.json`, registry или lock.
Неизменённые Java/fish/Workspace и три assets 2.5.2 остаются под исходными
source/digest pins. В конфигурации disjoint deployment меняется только
Community `PL_IMAGE` на прочитанный публичный digest; final135 delivery exports
не нужно повторять из-за Community-only patch. Точная byte-equivalence registry
и lock подтверждена отдельной accepted Source-проверкой; здесь нет claims о
всех четырёх образах253 или новой квалификации grading.

Source CI и публикация не заменяют Gateway2.2.0/реальный HTTP/bootstrap/raw-file
proof. Production остаётся остановленным до отдельной конечной приёмки mappings,
freshness, сохранности зачёта/кода и назначения ROOT на cutover.
