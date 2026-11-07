# Локальный Git Workspace

Image находится в `images/sp-git-workspace`. Он добавляет fish 3.7.0-1 и
Python 3.12.3-0ubuntu2.1 к закреплённому linux/amd64 образу
`docker.io/prairielearn/workspace-vscode-base@sha256:cdad0b1fd89a3e019efca29c66768ffa2f7b4f99dbfe3016e2667f6769b90600`.
Git и Code Server поставляются этим base; fish — выбранная оболочка Linux.
Новых служб авторизации нет: HTTP/code-server использует обычный native
Workspace proxy PrairieLearn. Образ работает с UID/GID 1001:1001.

Native exporter кладёт trusted student ZIP и manifest в `workspace/.pl-seed`.
Manifest `pl-git-workspace-seed-v1` содержит список путей `files:[string]`.
Первая инициализация проверяет ZIP, пути, типы, состав файлов и чистый Git seed
с одним исходным commit на `main` до атомарного переноса work. Проверку
Git object/index выполняет штатный Git; собственных SHA/форматов квалификации нет.
Вся переданная object database, включая packed и недостижимые объекты,
должна совпадать с замыканием A; готовые B или отдельные answer blobs в seed
отвергаются. Эта проверка выполняется только при первой инициализации:
недостижимые объекты существующей студенческой работы при restart сохраняются.
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

## Будущая изолированная квалификация Workspace

Полный маршрут native host, авторизации, proxy, save/resume и преподавательской
сдачи проверяется отдельно от локального lifecycle и container smoke.
Следующая процедура требует отдельного разрешения на server/auth/host действия;
сама инструкция такого разрешения и результата проверки не даёт.

1. Выбрать независимо проверенный исходник и immutable image identity. Создать уникальный scope ID, отдельные disposable course/jobs/volume и закрытый disposable конфигурационный каталог. Никакие существующие course, student home/volume, credentials или результаты не монтируются.
2. До запуска определить точный набор собственных ресурсов: новые контейнеры, volume, network. Каждому назначить scope labels и уникальные имена. Создать отдельную private internal bridge network; не присоединять инфраструктуру пользователя или внешнюю сеть.
3. PL публикуется только на loopback с выделенным свободным портом. Editor доступен через private Workspace proxy; его порт не публикуется на host. До работы сохранить фактические inspect-сведения собственных ресурсов: immutable image, labels, mounts, network membership и port bindings.
4. Проверить отрицательно отсутствие host-публикации editor, отсутствие wildcard/внешнего bind PL и отсутствие посторонних mounts/networks. При несовпадении прекратить qualification и сохранить диагностику, не подключать реальные student data.
5. Выполнить только в этом scope first seed, restart со split index/worktree, сохранение B, proxy/auth, save/resume и преподавательскую сдачу. Локальные seed/restart/HTTP checks сами не объявляют host/auth PASS.
6. До очистки сохранить результаты и перечень ресурсов по точному scope label. Останавливать и удалять только ресурсы этого запуска по их точным ID с повторной сверкой labels; глобальные prune, выбор старых контейнеров по общему имени и удаление существующих volume запрещены. При неизвестном состоянии оставить собственный ресурс с явной диагностикой для оператора.

Точный исходный PrairieLearn, по которому проверяется маршрут этого кандидата:
`92584fe426ececb84bc2d09de9975c7056c0c5f6`. Его schema/source и base image —
разные закреплённые зависимости; Docker Hub tag не доказывает source revision
base. Пакеты apt закреплены явно; итоговая поставка требует image digest и
сохранённого package inventory, поскольку транзитивные apt packages могут
обновляться в репозитории.
