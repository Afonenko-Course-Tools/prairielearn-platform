# Native delivery4: текущая реализация

Поставка4 содержит закрытый `kind`: `project`, `native-answer` или `workspace`.
`project` после удаления только `kind` сохраняет точные method-specific поля3.
Поставка3 остаётся отдельным строгим контрактом. Job2, Result1, qualified maps и
области `sourceSnapshotHash`, `inventoryHash`, code-only `verificationInventoryHash`
не переименованы. Internal получает отдельный `native-answer-package-v1` proof
в delivery-verification4: deliveryHash, qualifiedId, UUID, public slots и hashes
фактических HTML controls/server bytes. Private answer остаётся в server.py.
Manual/Workspace не получают фиктивный Job или runtime.

Workspace reader ограничивает размер ZIP, число/размер записей, проверяет exact
manifest inventory, пути, типы и aliases, Git object closure A/main, index/tree/
worktree и публичные common-file bytes. ZIP/receipt/seed reader не исполняет.
Producer прежнего same-operation пути проверяет include-git/common-files и
currentness до передачи seed. DTO или hash не создаёт права materialization.

Новый runtime-image receipt3 объявляет public4; receipt2/public3 остаётся строгим.
Published registry2 сохраняет grader profiles и отдельный закрытый
`workspaceImages.sp-git-workspace-v1.image`. Источник — source/asset-validated
release Context с отдельным Workspace image role. Обычный grader image этой
полномочности не даёт. Production registry/pins не изменены; реальный Workspace
image ещё не квалифицирован. Unit registry/digest являются вымышленными.

C render передаёт Core lease только data-only args/stdout/stderr/timeout.
Executable/cwd/closed env/profiles/token и pre-child fences принадлежат Core496.
Независимая квалификация G/S/K/L/R/M/E/prior-P, реальные assignment CLI positives,
whole135, OCI, installed и release остаются открыты. Publish сохраняет явный
`PL.NATIVE_RELEASE_UNQUALIFIED`. Ordinary/injected builder fixtures не заменяют
эти gates. Standalone Figure с RawBlock/RawInline по-прежнему явно отвергается;
произвольный HTML не разрешён и узлы не удаляются молча.

## Адресная коррекция index/build reader

Workspace index v2 сравнивается с initial A tree по точным path/mode/OID и stage0.
Количество и encoded UTF-8 pathname length должны совпадать с
читаемым bounded index. Stat cache (ctime/mtime/dev/inode/uid/gid) не является
содержимым Git дерева и не закрепляется произвольными timestamp-проверками.
Подтверждённые mode/type и pathname-length mutants отвергаются до proof. Reader
не запускает Git; реальный `git diff --cached --raw HEAD` используется только на
собственном тестовом seed для различающего контроля.

`build-course.py` применяет существующий `package_integrity` к закрытым3/4 после
export и до provenance/атомарной выдачи candidate. Это проверяет реальные native
project/Internal/Workspace semantics, не создавая фиктивный code Job. Source-bound
release capability проверяется отдельно; legacy receipt2(public3) не допускает4.
Clean-source, final/recheck и no-replacement fences сохранены. Legacy3 положительный
fixture теперь содержит полный closed3 пакет вместо UUID-only stub. Выдача
локального UNIT candidate не является release/assignment/image qualification.

## Обязательное расширение index tail

После index entries reader разбирает extension headers до SHA1 footer. Неизвестное
mandatory расширение (первая буква signature вне ASCII A–Z) получает отказ до
package/receipt proof. Uppercase optional пропускается по declared size, как в
проверенном Git. Доказанное игнорирование oversized TEST без payload и короткого
остатка сохранено; дополнительных length/order ограничений не добавлено. Это
data-only проверка: Git запускается только над собственным UNIT seed в тесте.
