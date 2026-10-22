# Версии Platform и публикация образов

`VERSION` содержит **2.3.0** — локальную кандидатуру с новым opt-in Gradle JAR profile и совместимыми классическими JUnit-профилями. Публикация2.3.0 не выполнена; новые OCI digests отсутствуют.

Действующие образы **2.2.0** опубликованы из commit
`b7fd40c42f3bbe03d0bb94111cde392c74c11b32`; source tag выпускается после
проверки metadata commit с фактическими pins.
Исторический receipt2.2.0 объявляет delivery/results2; эти опубликованные bytes сохранены.
Кандидат2.3.0 использует текущий native delivery3 и results2 при receipt schemaVersion2
и неизменном Tool API2.1.0. Body/delivery/results используют
позиции: каждый native экземпляр выбирает один вопрос каждой позиции, все кандидаты
остаются в каталоге. Прежние delivery/results отклоняются до sync/Bridge операций.

| Интерфейс | Текущий контракт |
| --- | --- |
| `check-course.py inventory/verify`, `grading_job.py`, build/sync | Tool2.1.0 |
| Native delivery кандидата2.3.0 / Gateway results | schemaVersion3 / schemaVersion2; per-slot-results-v2 |
| Completion | required-slot-completion, позиции requiredSlotIds |
| Runtime registry, grading descriptors/jobs, check results, verification receipts, contract cases | schemaVersion1, отдельные закрытые schemas/ |
| Project check | project-check.schema.json, без отдельного schemaVersion |
| Enrollment, assignment и work launch | Закрытые named schemas; assignment.version — ревизия предоставления доступа |
| Native course registry / image lock | pl-courses-v2 с institution key; legacy v1 только staging / pl-images-v1 |
| Каталог учреждений | pl-institutions-v1; config/institutions.json; numeric ID разрешается native model |
| Опубликованные профили Java2.2.0 | java25-junit-v1 и java25-mutation-v1, образ java25-grader |
| Кандидат Java2.3.0 | прежние два профиля и opt-in java25-gradle-junit-v1; отдельная локальная приёмка, без нового published pin |
| Текстовый профиль | fish-git-v1, собственный образ fish-git-grader |
| Java/JUnit | Java25, JUnit console1.14.1, JSON simple1.1.1 |

Registry закрепляет runner и полный набор зависимостей по hash. Образ должен
 соответствовать этому набору. [runtime-image.json](../runtime-image.json)
 содержит фактический исходный commit сборки и опубликованные OCI digests версии
 2.2.0; [runtime-profiles.json](../runtime-profiles.json) связывает каждый профиль
 с соответствующим образом. [images.lock.json](../images.lock.json) закрепляет
 базы и служебные образы. Source tag может включать следующий commit с metadata;
 различие исходников сборки и итогового tag должно ограничиваться metadata и
 документацией, с сохранением runner/library hashes.

Publisher [39018028757](https://github.com/Afonenko-Course-Tools/prairielearn-platform/actions/runs/39018028757)
завершил сборку, проверки, публикацию и pull всех трёх digests. Checked-in receipt
и registry совпадают побайтово с его artifacts; SHA-256 registry —
`195eafb709cdd57589e0b626861bc8feb44d58a3c78a4520d0da04e620050650`.
Java/fish version tags и все три digest доступны при анонимном pull; OCI source
labels указывают на исходный commit выше. Это подтверждает публикацию образов;
приёмка реального Moodle и серверного deployment выполняется отдельно.

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

## Подготовка кандидата2.3.0

Из clean checkout Python3.14+ запускает `tools/prepare_native_toolchain.py --fetch`: фиксированные HTTPS inputs проверяются по size/SHA, public keyring → gpgv → InRelease → Packages → exact package stanza, затем извлекаются только три regular JNI-компонента. Для уже имеющегося owner-controlled cache команда без `--fetch` повторяет все проверки без сети. Installer работает только внутри trusted Dockerfile build; host не исполняет JDK/Gradle/installer и не устанавливает package.

Команда `--write-build-context /private/fresh.tar` создаёт новый детерминированный allowlisted TAR; genuine Dockerfile build получает его через stdin. Поэтому содержимое checkout/cache за пределами COPY closure не передаётся builder даже в legacy режиме. Generated `.native-toolchain` содержит закрытый manifest,3 dependency-only Java profiles без image, generated316/319 locks, exact helper81cd и inputs одного source HEAD. `--verify-context` запрещает dirty/source drift, extra/missing/modified files и подменённый baked view. Прежние runtime receipts не копируются. Старые опубликованные registry/images.lock остаются действующими pins2.2.0.

Новый отдельный CI job выполняет preparation, genuine clean Dockerfile build и конечный synthetic image smoke; старый contracts job15min сохранён. Python action закреплён точным [upstream commit](https://github.com/actions/setup-python/commit/83679a892e2d95755f2dac6acb0bfd1e9ac5d548). Initial fixed input/base fetch отделён от offline RUN. Выбран legacy builder `DOCKER_BUILDKIT=0`; если он недоступен либо фактическая resolver/offline граница не доказана, build gate открыт и fallback не допускается. Одних `--pull=false --network=none` недостаточно для приёмки. Конфигурация workflow сама по себе не является результатом CI.

Перед разрешённой публикацией нужны независимый source/context review, actual clean build/readback319+316/716 и конечный runtime/privacy smoke. Прежняя локальная phase18 с восемью outcomes сохраняется только для своего exact source/image snapshot. После одобренной публикации нужны настоящий OCI digest, независимый pull/readback, coherent external registry и последующая course/Moodle приёмка. Локальный image ID или новый VERSION этого не заменяют.

## Проверенная последовательность публикации

1. Независимо проверить точную вершину PR, три Dockerfile и publisher workflow;
   выполнить owner suites. После merge зафиксировать actual merged SHA и сравнить
   дерево с проверенной кандидатурой.
2. Запустить Publish reviewed Platform images на main с новым номером из VERSION:

   ```sh
   gh workflow run publish-runtime.yml --ref main -f version=2.3.0 \
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
   deliverySchemaVersion3, resultsSchemaVersion2 и runtimeProfilesSha256. published-runtime-profiles.json
   связывает три Java профиля с java25-grader, fish с fish-git-grader. Producer проверяет
   clean source HEAD/version и весь prepared context; Java pins берёт из его
   проверенного baked view, fish pins — из фактических файлов того же source HEAD.
   Скачать artifact
   platform-runtime-digests-VERSION, проверить sourceCommit и сохранить receipt и
   registry как release assets. `published-toolchain-lock.json` из того же artifact
   содержит generated lock с SHA `c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca`.
   В отдельной release assembly он занимает существующий путь
   `runtime/gradle-jar-v1/toolchain-lock.json`, а registry — `runtime-profiles.json`;
   остальные dependency files и оба runner берутся побайтово из указанного source commit.
   Существующий `grading_job.runtime_evidence` должен проверить полную closure каждого
   из четырёх профилей в этой assembly до её использования. Исходный checkout с
   canonical prepared-status lock SHA `6c847e7b52f9280f7666bb7e78b781f761160c0323f34eb4832336f2938f7ca6`
   сам по себе не соответствует published lock pin; canonical lock не переписывается,
   иначе перестанет работать воспроизводимая подготовка. Эта assembly не является новым
   runtime API или свидетельством выполненной публикации.
   Metadata commit обновляет checked-in pins по этим
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
