# Приватный Bridge входа и зачисления

Platform Bridge работает внутри закреплённого Community на отдельном приватном listener и использует native enrollment, permissions и authz модели. Native user/session остаются собственностью PrairieLearn. Gateway не получает DB credentials и не передаёт SQL, native IDs или произвольные staff роли.

Единственный маршрут — `PUT /internal/gateway/enrollment` без query. Нужен service bearer длиной не менее 32 символов из `tokenFile`; browser cookies и identity headers не аутентифицируют вызов. Остальные маршруты и методы получают 404 после bearer проверки, до чтения тела и native операций. Публичный proxy закрывает `/internal/`; Bridge не должен иметь публичного порта.

## Конфигурация

Private settings содержат только `listenHost`, `listenPort`, `tokenFile`, `administratorEmail` и `bindings`. `administratorEmail` — canonical email либо `null`, по умолчанию `null`. Каждый binding содержит ровно `courseKey`, `instance`, `courseId`, `courseInstanceId`, `courseInstanceUuid`. IDs — положительные десятичные строки; UUID и значения берутся из фактической native регистрации курса и экземпляра. Пара `courseKey`/`instance` однозначна.

`mode`, `administratorUid` и `deliveryPath` запрещены. Альтернативного grading или login-only режима нет. Delivery manifest, работы и assignment labels не участвуют в запуске или зачислении Bridge. Перед подключением DB сервер требует `NODE_ENV=production`, `devMode=false`, `hasShib=true`. Deploy config должен соответствовать этому единственному формату.

Единственный [пример private settings](../config/pl.gateway.example.json) содержит вымышленные native IDs и UUID. Оператор заменяет их данными фактической регистрации, задаёт `tokenFile` и при необходимости доверенный `administratorEmail`; `null` оставляет Administrator grant выключенным.

В `compose/compose.gateway.yml` Bridge получает только private config и token. В `compose/compose.prod.yml` native каталог курса монтируется в `/course` только у PL. Gateway получает private config и своё постоянное хранилище; файлы курса и delivery ему не нужны.

## Запрос и native доступ

Запрос соответствует [закрытой схеме](../schemas/gateway-enrollment.schema.json) и содержит ровно пять обязательных полей:

```json
{
  "userUid": "student@fixture.invalid",
  "instance": "fall",
  "courseKey": "demo",
  "role": "student",
  "email": null
}
```

`userUid` содержит от 1 до 512 символов, `instance` непустой, `courseKey` соответствует `^[a-z][a-z0-9-]*$`, `role` — только `student` или `teacher`. Email — canonical lowercase ASCII mailbox без пробелов и управляющих символов: до 254 символов, local part до 64 без начальной, конечной или двойной точки, домен минимум из двух DNS labels до 63 символов. Bridge не нормализует адрес; `+alias` остаётся отдельным email. Поле `email` обязательно, даже при `null`.

Gateway передаёт доверенные роль и email из проверенного подписанного LTI контекста своей регистрации и исходной сессии. Если доверенный email недоступен, передаётся `null`. Этот контекст принимается только за private service bearer.

На каждом входе Bridge сверяет native CI по ID, course ID, UUID и short name и отклоняет удалённый экземпляр. Пользователь выбирается только по существующему `userUid`; неизвестный UID получает 404. Email не вычисляет identity, не объединяет пользователей и не меняет native IDs.

В native транзакции advisory lock по экземпляру и UID сериализует зачисление и grant. Blocked enrollment отклоняется до ensure для всех ролей; затем требуется joined enrollment. После доверенных grants Bridge вызывает native `constructCourseOrInstanceContext` для того же user/course/instance. Как штатный `authzHasCourseInstanceAccess`, проверка допускает фактический course preview или instance view, либо Student access с enrollment. Для пользователя без native staff прав дополнительно сохраняется требование modern publishing; неопубликованный или закрытый для Student экземпляр отклоняется. Отказ не возвращает путь и откатывает транзакцию.

Проверка использует `is_administrator: false`: global Administrator без активного native admin mode cookie не считается автоматически staff этого курса. Teacher и владелец получают scoped staff-права до проверки публикации, поэтому первый доверенный вход в закрытый для Student курс возможен. Прежние native staff-права также учитываются при входящем `role: student`, без новых grants. Реальные browser mode, cookie и дальнейший доступ по URL по-прежнему проверяет PL.

## Доверенные права

Точное совпадение `email` с private `administratorEmail` выдаёт native global Administrator и scoped `Editor` курса + `Student Data Editor` экземпляра при обеих ролях, включая `role: student` для Moodle Learner. Для владельца оператор задаёт доверенный canonical адрес в конфигурации. Адрес не встроен в handler и не определяет UID.

Остальные Teacher получают native `Editor` курса и `Student Data Editor` экземпляра через штатные permission API. После API проверяются прежние native user ID/UID и фактические права. Student с другим email новых staff/admin прав не получает. Права additive: повторный вход и смена входящей роли на Student не отзывают ранее выданные Owner, Editor или Administrator.

Administrator SQL связывает UID и native user ID как при вставке, так и при повторной проверке. `ON CONFLICT DO NOTHING` сохраняет идемпотентность; native audit создаётся только из новой administrator записи, с тем же native user ID в качестве actor. Grant и enrollment проходят в одной транзакции после identity/blocked/joined guards; итоговый native staff-or-student access проверяется до commit.

Native semantics сверены с закреплённым Community `92584fe426ececb84bc2d09de9975c7056c0c5f6`: [построение course/instance authz](https://github.com/PrairieLearn/PrairieLearn/blob/92584fe426ececb84bc2d09de9975c7056c0c5f6/apps/prairielearn/src/lib/authz-data.ts), [допуск staff или enrolled Student](https://github.com/PrairieLearn/PrairieLearn/blob/92584fe426ececb84bc2d09de9975c7056c0c5f6/apps/prairielearn/src/middlewares/authzHasCourseInstanceAccess.ts) и [native admin mode](https://github.com/PrairieLearn/PrairieLearn/blob/92584fe426ececb84bc2d09de9975c7056c0c5f6/apps/prairielearn/src/lib/authn.ts). Gateway передаёт доверенный контекст и открывает возвращённый native путь; собственную role/email policy он не добавляет.

## Ответ и ограничения

Успешный [закрытый ответ](../schemas/gateway-enrollment-response.schema.json) содержит ровно `schemaVersion: 1`, `userUid`, `instance`, `courseKey`, `enrolled: true`, `path: /pl/course_instance/<positive native integer>/assessments`. Путь строится из проверенного native экземпляра, без origin, query или suffix. Роль и email в ответ не включаются. Все ответы используют `Cache-Control: no-store`; размер тела ограничен 8192 байтами, внутренние ошибки скрыты.

Assignment, grades, results, work-launch и отдельный admin-bootstrap HTTP handlers удалены. В `bridge/native.sql` остались advisory lock и administrator grant/audit. SQL миграций таблицы заданий больше нет; исторические данные не удаляются и запросы к реальной DB при этой переработке не выполняются. Отдельное [native административное признание результата](recognized-credit.md) и его guards сохраняются.

Локальная проверка без DB, HTTP listener или контейнеров:

```bash
node tests/bridge/enrollment.test.mjs
node tests/bridge/administrator.test.mjs
python3 tests/bridge/enrollment-schema.test.py
node tests/recognized-sql.test.mjs
```

Harness исполняет настоящий settings/context/enrollment/router, заменяя native DB/models и listener. Проверка PostgreSQL parser и native binder не исполняет SQL. Эти проверки не заменяют отдельный native DB/Moodle/UI smoke и подтверждение настоящих audit records.
