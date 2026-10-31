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
