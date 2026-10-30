# Локальный Git Workspace

Image находится в `images/sp-git-workspace`. Он добавляет fish 3.7.0-1 и
Python 3.12.3-0ubuntu2.1 к закреплённому linux/amd64 образу
`docker.io/prairielearn/workspace-vscode-base@sha256:cdad0b1fd89a3e019efca29c66768ffa2f7b4f99dbfe3016e2667f6769b90600`.
Git и Code Server поставляются этим base; fish — выбранная оболочка Linux.
Новых служб авторизации нет: HTTP/code-server использует обычный native
Workspace proxy PrairieLearn. Образ работает с UID/GID 1001:1001.

Native exporter кладёт trusted student ZIP и manifest в `workspace/.pl-seed`.
Manifest `pl-git-workspace-seed-v1` содержит `sha256` архива и
`files:[{name,sha256}]`. Первая инициализация проверяет ZIP, paths/types,
inventory/hashes и чистый Git seed с одним A/main до атомарного переноса work.
`identity.json` связывает выбранный архив с исходным commit. Обычный restart
читает identity и продолжает существующее work без Git refresh и без записи
в HEAD/index/worktree. Работа без identity, identity без work и изменённый seed
получают отказ с сохранением bytes. Прерванный старт между work rename и записью
identity также требует адресного восстановления: автоматического reset нет.

Передача сдачи принадлежит native host. Для раннего плоского Git-проекта
exporter требует `gradedFiles` с `work/**`, `work/.git/**`, `work/.*`,
`explanation.m[d]`, `.pl-seed/identity.jso[n]`. ZIP студента в Workspace не требуется.
Эти шаблоны не обещают перенос произвольной вложенной структуры дополнительных
скрытых каталогов; расширенная квалификация остаётся открытой.

Локальные проверки:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/sp-git-workspace -v
docker build --pull=false -t local/sp-git-workspace:candidate images/sp-git-workspace
PYTHONDONTWRITEBYTECODE=1 python tests/sp-git-workspace/container_smoke.py local/sp-git-workspace:candidate
```

Container smoke создаёт собственный временный volume и удаляет его после
проверки. Он проверяет UID1001, fish/Git, повторное создание контейнера с тем же
томом после первого restore, B до второго restore и HTTP health Code Server.
Тест не обращается к portal, не создаёт попытки и не квалифицирует native host,
авторизацию или возврат сдачи в интерфейсе преподавателя. Производственный
OCI digest и включение в установленный курс закрепляет интегратор после
независимой рецензии. Временная локальная tag не является release identity.

Точный исходный PrairieLearn, по которому проверяется маршрут этого кандидата:
`92584fe426ececb84bc2d09de9975c7056c0c5f6`. Его schema/source и base image —
разные закреплённые зависимости; Docker Hub tag не доказывает source revision
base. Пакеты apt закреплены явно; итоговая поставка требует image digest и
сохранённого package inventory, поскольку транзитивные apt packages могут
обновляться в репозитории.
