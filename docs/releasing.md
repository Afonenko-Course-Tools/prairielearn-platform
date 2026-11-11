# Публикация образов Platform

Dockerfile Java grader устанавливает JDK25 и Gradle обычной поставкой образа.
Собственных toolchain-lock, нормализатора JDK, подготовительного inventory,
allowlisted context archive и release assembly больше нет. Gradle отвечает за
сборку, Docker — за содержимое образа. OCI digest остаётся штатным идентификатором
Docker; повторной проверки SHA каждого файла образа перед заданием нет.

Этот документ описывает новый Source candidate. Локальный Docker build и
публикация нового image этим изменением не подтверждены. Ранее сохранённые
образы, VM, данные и результаты не переключаются автоматически.

## Проверка кандидата

Из корня репозитория:

```sh
python3 -m unittest discover -s tests -p test_plain_runtime.py -v
docker build -f images/java25-grader/Dockerfile -t local/platform-java:review .
PL_TEST_IMAGE="$(docker image inspect local/platform-java:review --format '{{.Id}}')" python3 -m unittest discover -s tests -p test_plain_image.py -v
```

Первый маршрут проверяет реальное публичное grader поведение на host JDK25.
Второй проверяет тот же смысл в фактически собранном образе. Ошибка сборки или
недоступный Docker не являются успешной проверкой; нельзя заменять их старым
image либо unit double. Права, отдельные роли и доступ к trusted tests проверяются
отдельно от наличия правильного ответа.

Полный выпуск также проверяет Community, fish и Workspace. Обычный CI не получает
старую assembly с generated locks и не запускает старый c020 source ради proof.
Обновление курса Native и Moodle не следует из успешного image smoke.

## Подготовка публикации

После независимой рецензии точной версии и итогового просмотра разрешённый
координатор запускает `publish-runtime.yml` с `version`, `reviewed_commit` и
`components`. Режимы `all`, `community` и `java` сохраняют отдельные задания.
До всех image checks выбранного режима pushes не выполняются. Публикация не
входит в текущий локальный пакет; этот workflow здесь не запускался.

Полный режим `all` получает фактические Java/Community/fish/Workspace OCI digests после
push и pull и вызывает `tools/publish-metadata.py`. Команда создаёт два обычных
JSON файла:

- `runtime-image.json`: sourceCommit, version, images и поддерживаемые версии
  протокола delivery/results;
- `published-runtime-profiles.json`: три Java профиля, fish и отдельный Workspace
  image reference при его наличии.

Publisher проверяет соответствие image роли и sourceCommit/VERSION checkout.
Он не создаёт собственных hashes файлов, source tree inventories, generated
locks или filesystem currentness proof. `runtimeProfilesSha256` и
`published-toolchain-lock.json` удалены. Для нового API совместимость со старой
assembly не предоставляется. Git commit и OCI digest сохраняют происхождение
версии, но сами по себе не доказывают корректность grader.

Четыре pushes не атомарны: при частичной публикации сохраняются фактические
логи и digests. Повторное использование уже опубликованного номера и
переключение deployment требуют отдельного решения. Обычный Docker context
ограничивается `.dockerignore`; данные студентов и секреты не передаются builder.

## Отдельный Java выпуск

`components=java` требует точный independently reviewed commit уже в `main`,
совпадение dispatch SHA, checkout HEAD и `reviewed_commit`, а также равенство
`VERSION` выбранному новому semver. Существующий registry tag блокирует выпуск;
ошибка сети или авторизации не считается доказательством отсутствия tag.

Перед push выполняются Java grader source contracts с настоящим JDK25,
отрицательные binding/diagnostic проверки и `test_plain_image.py` на immutable
ID только что собранного образа. После push workflow делает настоящий pull
полученного OCI digest. Прочитанные image ID, source URL и revision label должны
совпадать с проверенным образом и reviewed source. Номер версии сам по себе
не заменяет эти проверки.

Artifact `platform-java-digest-<version>` содержит `java-image.json` с прежними
полями `version`, `source_commit`, `repo_digest`, `image_config_id`, отдельный
`java-image.txt` и полный `java-image-inspect.json`. Координатор читает эти
assets из завершившегося hosted run до переключения deployment. Community,
fish и Workspace этим режимом не пересобираются и не получают новые digests.
Локальные проверки shell guards не подтверждают настоящий registry push/pull.

## Native delivery

Текущий exporter передаёт delivery v5 и отдельные private checks v3.
`check-course.py verify` проверяет фактические selected bytes и поведение grader;
Bridge и Gateway сохраняют свои проверки UUID, принадлежности и прав. CI и
publisher выполняют текущие Python/bridge contracts без отдельного экспорта
невостребованных synthetic delivery4 fixtures и без второго receipt допуска.

Для локального preview используется стабильный writable course path и штатный
native loader из [маршрута разработки](development.md). `stage_courses.py`
сохраняется как ручной инструмент read-only снимков точного Git commit; он не
заменяет writable Git checkout штатного sync и не является командой обновления
preview. Старые документы выпуска и данные сохраняются.
