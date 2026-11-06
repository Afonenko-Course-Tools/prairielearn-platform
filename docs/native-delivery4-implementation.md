# Native delivery v5: текущая реализация

Название файла сохранено для существующих ссылок. `classification` в
`tools/delivery_verification.py` принимает только `schemaVersion: 5`.
Поставка содержит каталог вопросов, работ и экземпляров курса, список файлов
и закрытые bindings с `kind: project | native-answer | workspace`.
Собственных hash-полей и отдельного package-proof envelope у этого контракта нет.

`project` явно задаёт `grading.method`, UUID, `sourceRoot` и форму сдачи.
Для `external`/`mixed` дополнительно нужны runtime, project-check и выбранные
источники. `package_integrity` сопоставляет binding с фактическими native
JSON, controls и приватным дескриптором проверки. Ручной проект не получает
автоматический Job; приватные tests, server и внешний grader для него запрещены.
Редакторы и загрузка проверяются по реальному составу starter и источников.

`native-answer` задаёт тип ответа, публичные `responseSlots`, UUID и способ
оценивания. `binding4` проверяет структуру slots, а `native_proof` — соответствие
HTML controls этим slots и наличие `server.py`. Несмотря на историческое имя,
`native_proof` не создаёт hash DTO. Приватный ключ остаётся в `server.py`;
`showCorrectAnswer` должен быть `false`, политика `partialCredit` должна
соответствовать способу оценивания. Такой вопрос не получает code Job.

## Workspace и штатный Git

Workspace — ручной проект с `singleVariant: true`, элементом `pl-workspace`
и точными `workspaceOptions`. Image в binding задаётся через `@sha256:`;
это native OCI identity. Поля gradedFiles должны возвращать рабочие файлы,
Git state, пояснение и identity первоначального seed.

`seed_proof` читает архив и manifest `pl-git-workspace-seed-v1` со списком путей
`files:[string]`. Он ограничивает размер ZIP, число и размер записей, проверяет
состав, пути, типы, aliases и совпадение публичных копий исходников и архива.
Небезопасные config, внешнее Git state и подмена типов файлов запрещены.

До проверки содержимого `git cat-file --batch-all-objects` сообщает размеры всех
объектов, включая packed и недостижимые; объект больше 8 MiB отвергается.
Вывод каждой команды ограничен 8 MiB, память процесса — 256 MiB, CPU и
время ожидания — 20 секундами.

Git проверяет временную копию seed штатными командами `fsck`, `rev-list`,
`diff-index`, `ls-tree` и `cat-file`: требуется один исходный commit на `main`,
совпадающие index/tree/файлы и отсутствие объектов вне исходного дерева.
Поддерживаемые Git форматы, включая packed objects и index v4, читает сам Git.
Symlink/submodule и лишние начальные файлы отвергаются. Stat cache не служит
подтверждением содержимого: bytes каждого файла сравниваются с `git cat-file blob`.
Содержимое ZIP и hooks не исполняются; внешние Git environment/config отключены.
Собственного разбора object/index и вычисления SHA у reader нет.

## Потребители и границы проверки

`build-course.py` требует чистый исходный checkout и свежий внешний output,
запускает установленный exporter, затем проверяет выбранные checks,
`package_integrity`, UUID и assessments перед атомарной выдачей каталога.
Приватные checks записываются отдельно от дерева, которое читает PrairieLearn.

`check-course.py --scope delivery` проверяет фактический native пакет и
запускает сценарии только для автоматических `project`. При отсутствии таких
проектов отчёт содержит `automatic.state: not-applicable` с причиной
`no-project-automatic`; фиктивные jobs/results/score не создаются.
`package_integrity` возвращает `status` и `questionBindings` без hash receipt.

Текущий `runtime-profiles.json` содержит `schemaVersion: 1` и grader profiles
с native OCI image digests. Эта проверка пакета не подтверждает доступность
Workspace image, выполнение полного курса, реальный запуск в PrairieLearn или
браузерную приёмку. Локальные fixture-проверки не заменяют эти наблюдения.
