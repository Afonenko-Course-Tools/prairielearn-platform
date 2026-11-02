# Перенос признанного результата и приватного кода

Это внутреннее расширение административной границы Community, а не публичный endpoint сдачи. Исходный полный автоматический успех даёт обе текущие компоненты IQ: например, 80 автоматических +20 ручных либо 0+100 для manual-only. Признание не означает прохождение новых тестов. Общие `force_max_points`, параметры оценивания, старые ответы и автоматические jobs не меняются.

## Административная запись

E вызывает `tools/recognize-credit.mjs::recognizeMappedCreditAndFiles`. Обычный путь вызывает новый экспорт существующего native `manualGrading.recognizePreviousCredit`; модуль `bridge/recognized-credit-native.mjs` реализует этот ограниченный native режим. Внешний E-adapter не выполняет SQL UPDATE оценок. Native функция берёт штатный AI lock, проверяет фактического администратора, исходный незакрытый отменой Internal/External success и точное назначение, пишет существующие `audit_logs`/`question_score_logs`, ставит обе компоненты, `complete` и pending=false и вызывает штатный aggregate recompute. Состояние открытия AI/IQ сохраняется.

Ключ включает capture/БД/job/submission/UID/native user и course ID+UUID, CI ID+UUID, work/assessment ID+UUID, question/AQ/AI/IQ и хеш одобренной строки карты. У Community `courses` нет колонки UUID: numeric course ID/path проверяются native join, UUID — по `infoCourse.json` этого native курса. UUID вопроса или похожее название сами по себе не доказывают соответствие упражнений.

Старые submission projections не переписываются. Для существующей точно подходящей submission возможен отдельный Manual job; без submission создаются native audit/score events, а не job с null submission и не фиктивный ответ студента. Уже существующий закрытый/неотвеченный IQ поддерживается. Отсутствующий selected IQ возвращает `NEEDS_NATIVE_ADMIN_EVENT`: административная материализация отсутствующего IQ ещё не реализована; эта строка не получает PASS и не подменяется другим случайно выбранным вопросом.

## Сохранение после новых действий

Четыре точечные границы src **и** исполняемого dist: сохранение submission; aggregate пересчёт (он же существующий путь request/gradable completion); отдельная ungradable completion; синхронизация/maxima перед zone computation. Guard восстанавливает только IQ с доверенным native событием и тем же исходным успехом. Он не переписывает новую неуспешную submission/job, не распространяется на другие IQ и не использует feedback как полномочие. При recognized IQ прежние precomputed zone points отбрасываются; остальное вычисляет штатная Native схема. Ошибка I/O или исходного свидетельства завершает текущую операцию ошибкой, без молчаливого частичного успеха.

Patcher принимает только десять точных исходных src/dist хешей pinned Community, проверяет все входы до первой записи и отказывает при повторе/дрейфе. Четыре hooks и административный экспорт — пять пар файлов; это не глобальный перехватчик.

## Приватные файлы

Закрытая карта перечисляет **все** выбранные references с UID, native source AI/IQ/user и либо submission/variant/полем raw или submitted/index, либо native file ID. У Workspace `_files` могут находиться только в `submitted_answer`: эти references отличаются от raw. Имя исходного файла отдельно от пути приватного пакета; разные сдачи с одинаковым именем не сталкиваются. Native source join и полные bytes/size/SHA проверяются до первого upload; E-entrypoint проверяет их и приватный пакет до признания оценки.

Назначение — существующий native file-store, `student_upload` с точными destination user/assessment/AI/IQ и отдельным admin actor. Native files не имеет поля submission: исходная связь с submission сохраняется в явной закрытой карте/audit, поле в таблице не выдумывается. Повтор ищет стабильное имя source-reference+hash и проверяет полные байты, не перезаписывает чужой файл. Все source references проверяются и при конечной assignment-привязке. Файлы не делаются публичными. Нужны доставленные personal notes и настоящий student download ACL; один admin `getFile` этого ACL не доказывает. Ошибка upload сохраняется, автоматического retry/удаления возможного orphan нет; перед отдельной повторной операцией — readback существующего native результата.

## Назначение и результаты

Добавлено одно nullable FK-поле к существующей `pl_gateway_assignments`. Для переноса bounded admin операция проверяет exact prior version/request hash, новый request/map/admin, Native recognition+все private files, снимает прежний managed ACL и назначает новый существующими enrollment/label APIs. Обычный `assignmentTransition` по-прежнему отказывает cross-delivery. Новый обычный request сбрасывает FK. Повтор сверяет текущее состояние без повторной записи ACL/version/FK.

Результаты используют только точный bound AI с Native event и теми же UUID/ID/UID/work/delivery, никогда произвольную прежнюю попытку. Если событие исчезло или устарело — отказ, а не fallback на latest. Обычный путь сохраняет activation date filter. Полный old→new mapping и UUID actual export сверяются отдельно; предварительно вычисленные IDs не являются разрешением начислить зачёт.

## Проверка

Локальные контролы исполняют реальные публичные functions и pinned Native src/dist, заменяя только внешние DB/model/file I/O. PostgreSQL WASM parser проверяет 27 SQL-блоков, AST состава записей и колонки по pinned Native schema; **SQL не исполнялся**. Source route/middleware контролы проверяют ветви Native download, но не подменяют настоящий HTTP/Native authz sproc.

Это новый, ещё не собранный Native образ. Принятый target252/c81f не содержит этих hooks и не квалифицирует перенос зачёта. Нужны независимая source-рецензия и последующий конкретный isolated build/micro-run Root. Production и сохранённые UNKNOWN/CLI не затрагиваются.
