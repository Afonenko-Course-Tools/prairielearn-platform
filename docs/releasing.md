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
PL_TEST_IMAGE=local/platform-java:review python3 -m unittest discover -s tests -p test_plain_image.py -v
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
`exporter_commit`. До всех image checks pushes не выполняются. Публикация не
входит в текущий локальный пакет; этот workflow здесь не запускался.

Publisher получает фактические Java/Community/fish/Workspace OCI digests после
push и pull и вызывает `tools/publish-receipt.py`. Команда создаёт два обычных
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

## Остаток Native delivery

В существующих `build-course.py`, `stage_courses.py`, Gateway и PL ещё есть
старый course delivery/verification contract. Он не становится новым целевым API
и не является частью удалённой runtime assembly. Одновременное удаление его
producer и обязательных readers принадлежит согласованному Native/Gateway
пакету; пока они не заменены, объявлять весь стек hashless нельзя. Старые данные
и файлы сохраняются. `--assembly-root` и `--admission-policy` обходы staging
удалены вместе с собственной authority assembly; обычный staging не переключался.
