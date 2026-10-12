# Версии Platform и публикация образов

Текущий исходный контракт — **2.0.0** (`VERSION`). Body/delivery/results используют
позиции: каждый native экземпляр выбирает один вопрос каждой позиции, все кандидаты
остаются в каталоге. Прежние delivery/results отклоняются до sync/Bridge операций.

| Интерфейс | Текущий контракт |
| --- | --- |
| `check-course.py inventory/verify`, `grading_job.py`, build/sync | Tool2.0.0 |
| Native delivery и Gateway results | schemaVersion2; per-slot-results-v2 |
| Completion | required-slot-completion, позиции requiredSlotIds |
| Runtime registry, grading descriptors/jobs, check results, verification receipts, contract cases | schemaVersion1, отдельные закрытые schemas/ |
| Project check | project-check.schema.json, без отдельного schemaVersion |
| Enrollment, assignment и work launch | Закрытые named schemas; assignment.version — ревизия предоставления доступа |
| Native course registry / image lock | pl-courses-v1 / pl-images-v1 |
| Профили Java | java25-junit-v1 и java25-mutation-v1, образ java25-grader |
| Текстовый профиль | fish-git-v1, собственный образ fish-git-grader |
| Java/JUnit | Java25, JUnit console1.14.1, JSON simple1.1.1 |

Registry закрепляет runner и полный набор зависимостей по hash. Образ должен
 соответствовать этому набору. [runtime-image.json](../runtime-image.json)
 содержит фактический исходный commit сборки и опубликованные OCI digests версии
 2.0.0; [runtime-profiles.json](../runtime-profiles.json) связывает каждый профиль
 с соответствующим образом. [images.lock.json](../images.lock.json) закрепляет
 базы и служебные образы. Source tag может включать следующий commit с metadata;
 различие исходников сборки и итогового tag должно ограничиваться metadata и
 документацией, с сохранением runner/library hashes.

## Диагностическая проверка кандидата

`build-course.py --runtime-registry PATH --candidate-image sha256:...` передаёт
экспортёру отдельный registry с image:null для проверяемого профиля и точный локальный
config ID образа. Экспортёр проверяет этот ID через docker image inspect и помечает
поставку candidate:true. Профили опубликованного registry остаются без изменений.
`check-course.py --runtime-registry PATH` использует тот же registry на prepare,
выполнение (включая public verification) и проверку receipt. `PL_LOCAL_IMAGE_ID`
задаёт локальный ID только для профиля image:null; опубликованный pin по умолчанию
имеет приоритет. `--backend container --scope delivery` проверяет реальную поставку.
Candidate не допускается к staging независимо от успешного diagnostic receipt.
Опубликованный repository@sha256 digest нужен для authoritative release проверки.

## Проверенная последовательность публикации

1. Независимо проверить точную вершину PR, три Dockerfile и publisher workflow;
   выполнить owner suites. После merge зафиксировать actual merged SHA и сравнить
   дерево с проверенной кандидатурой.
2. Запустить Publish reviewed Platform images на main с новым номером из VERSION:

   ```sh
   gh workflow run publish-runtime.yml --ref main -f version=2.0.0 \
     -f reviewed_commit=ACTUAL_MERGED_SHA
   ```

   Workflow проверяет branch/commit/version и использует scoped GITHUB_TOKEN
   contents:read/packages:write. Package должен предоставлять этому repository
   Actions access. Authentication/network ошибки не доказывают отсутствие tag.
3. Publisher требует доказанного отсутствия всех трёх registry tags. Отдельно
   собирает Java, Community и fish из точного checkout и закреплённых bases;
   отдельно проверяет каждый образ, Java/fish фактически в контейнерах. Все checks
   заканчиваются до pushes. Затем отдельно публикует три образа и получает их
   repository@sha256 digests; каждый digest проверяется docker pull.
4. Receipt schemaVersion2 содержит sourceCommit/version, три images,
   delivery/results2 и runtimeProfilesSha256. published-runtime-profiles.json
   связывает оба Java профиля с java25-grader, fish с fish-git-grader. Скачать artifact
   platform-runtime-digests-VERSION, проверить sourceCommit и сохранить receipt и
   registry как release assets. Metadata commit обновляет checked-in pins по этим
   фактическим digests; runner/library hashes сохраняются.
5. Проверить pull/package access с целевого узла, выполнить native/container/Moodle
   acceptance на опубликованных pins. Локальный image config ID и опубликованный
   OCI manifest digest — разные наблюдаемые идентификаторы.
6. После проверки pin commit поставить source tag и выпустить source/receipt/registry
   вместе. Downstream использует наблюдённые digests и точные source refs.

Три pushes не атомарны. При частичной публикации сохранить логи и перейти к новому
номеру для повторной проверенной публикации; существующий номер не перезаписывается.
GHCR tags изменяемы, deployment использует digests. Новая публикация сама по себе
не доказывает public visibility: нужный доступ подтверждается фактическим pull.

Первичные инструкции: [workflow dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
и [GHCR authentication/access](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
