# Community bridge

The Platform bridge runs inside the pinned Community image on a separate private
listener. Its source is based on Community commit
`92584fe426ececb84bc2d09de9975c7056c0c5f6`, image digest
`60c675a42055a430f9ad7298c7dfd2f37119aa471f806e21e2c929de28435f63`.
It imports native compiled enrollment/student-label models. Gateway has no database
credentials and never supplies SQL, native label IDs, or PrairieLearn staff roles.
The service uses native system authorization for its narrowly scoped mutations;
it does not assign any privileges to the Moodle teacher or Student.

Run the image with private config/token and read-only validated deliveries.
`compose/compose.gateway.yml` has no bridge host port. The public proxy must include
`proxy/nginx.gateway.conf`; the existing verified handoff callback remains a separate
identity path. Keep PL's HTTP and bridge listeners inaccessible from public clients.
The bearer token is a server credential of at least 32 characters, mounted as a secret.
Browser cookies and trusted identity headers do not authenticate bridge calls.
The bridge rehashes each configured delivery and every inventoried file at startup.
Private settings contain bindings from a delivery directory to a native instance ID;
the UUID in exported instance metadata must match that native instance.

`PUT /internal/gateway/assignments/{id}` accepts the closed request schema in
`schemas/gateway-assignment.schema.json`. Gateway sends only approved/assigned access,
or an explicit revocation (`newWork: null`). It must never call this for pending
requests. A first assignment has version 1 and null oldWork. Every replacement uses
version N+1 with oldWork equal to the previous newWork; identical retries reconcile
native ACL again. Stale/conflicting versions and identity changes fail. An assignment
journal row, enrollment, audit events and native label removal/addition commit in one
Postgres transaction. A per-user/instance advisory lock serializes changes; a unique
constraint prevents a second assignment ID from silently taking the same slot.
All other labels managed by the configured instance are revoked. Unrelated labels
remain. Native blocked enrollments cannot be bypassed.

`GET /internal/gateway/results?assignmentId=ID&version=N` requires the current active
assignment and native joined enrollment with its manifest label. It returns the
closed schema in `schemas/gateway-results.schema.json`; only manifest question IDs
are returned, with the latest attempt by number/ID (not the gradebook best score).
The SQL adapter lives in `bridge/native.sql`; dynamic client SQL is impossible.
Team assessments are excluded. Attempts created before the current assignment grant are excluded, including when a work is assigned again; idempotent retries preserve the activation time. A prior Homework attempt cannot be silently reused for a new grant. Such a workflow needs an explicit reviewed native reset/new-attempt policy before it can produce a new grade. Missing/ungraded questions have no completed credit.
Native question score_percent is normalized to 0..1; points/maxPoints remain visible.
Only exact score 1 on a completed required question contributes to completion.
Optional questions and two partial answers cannot satisfy pass-two-of-three.

The Platform journal persists in the PL database. It is not Gateway's workflow/outbox
store. Cross-delivery reassignment currently fails explicitly: deployment must reconcile
old managed ACL with a reviewed delivery-migration procedure before changing the binding.
Automatic privilege promotion, public write APIs and arbitrary assessment reads are absent.

Verification:

```
node tests/bridge/policy.test.mjs
PL_GATEWAY_BRIDGE_URL=http://private-pl:3001 \
PL_GATEWAY_TOKEN_FILE=/private/token \
PL_GATEWAY_DELIVERY=/private/native/delivery.json \
python3 -m unittest discover -s tests -p test_gateway_acl.py -v
```

The localhost-only patch permits a null cookieDomain in production solely when hostname equals localhost. This emits host-only cookies. Other production host/domain checks and encryption-key validation remain in force; devMode stays false. The patch script refuses a changed upstream guard rather than guessing.

Приёмка выпуска на изолированном стенде проверяет native Student список, прямые URL и повторное назначение, реальные оценки встроенного grader и интеграцию Gateway/AGS. Следуйте [порядку выпуска](releasing.md). Работающий listener и синтетическая строка оценки не подтверждают прохождение этих проверок.

## Зачисление и чтение обычных работ

В стандартном режиме `PUT /internal/gateway/enrollment` принимает ровно `userUid`, `instance` и `courseKey`
по схеме `schemas/gateway-enrollment.schema.json`. Нужен существующий пользователь
Community из проверенного callback. Bridge проверяет зарегистрированный binding,
UUID и отсутствие удаления native экземпляра, обеспечивает joined enrollment,
отклоняет blocked membership и проверяет опубликованный native Student доступ.
Повторный запрос сохраняет ту же учётную запись; неизвестный native UID получает 404.
В стандартном режиме роли, labels и assignment нельзя передать в запросе. Такое зачисление не выдаёт права
администратора, label или слот защиты.

Успешный ответ соответствует `schemas/gateway-enrollment-response.schema.json`:
`schemaVersion: 1`, те же `userUid`, `instance`, `courseKey`, `enrolled: true` и
`path: /pl/course_instance/<native id>/assessments`. Числовой ID берётся из
проверенного native экземпляра; курс и экземпляр из запроса не становятся URL.
Это штатный маршрут `studentAssessments` в закреплённом PrairieLearn source
`92584fe426ececb84bc2d09de9975c7056c0c5f6`, `apps/prairielearn/src/server.ts:1486`.
Gateway сначала выполняет проверенный Community handoff, затем использует этот
путь для открытия списка курса. Work, assignment и AGS для этого входа не нужны.

## Режим login-only и доверенные Moodle роли

Прежний config без `mode` сохраняет стандартный grading режим: полный
`loadVerifiedBindings`, проверки grading payload/candidate/OCI, прежние routes и
явный `administratorUid` остаются. Для отдельного входа в уже импортированный
native курс доступен только явный `mode: "login-only"`; пример —
`config/pl.gateway.login-only.example.json`. Вымышленные IDs и UUID примера
оператор заменяет результатом actual native DB join.

Login-only регистрирует private связку `courseKey`, `instance`, `courseId`,
`courseInstanceId`, `courseInstanceUuid`. Неоднозначная пара course/instance
отклоняется при запуске. На каждом входе native CI должен совпасть по ID,
принадлежности курсу, UUID и short name; удалённый CI отклоняется. Поля
`deliveryPath` и `administratorUid` в этом варианте запрещены: grading manifest
не становится источником доверия для identity. Production, bearer, existing UID,
blocked/joined enrollment и native Student publishing/access guards сохраняются.

Единственный разрешённый route — `PUT /internal/gateway/enrollment`. После bearer
проверки все остальные методы и assignment/results/work/admin routes получают 404
до разбора тела и native операций. Assignment DDL migrate при этом не запускается;
native enrollment, permission API и audit logs по-прежнему могут изменять native DB.

Private запрос содержит ровно пять полей: `userUid`, `instance`, `courseKey`,
`role: "student" | "teacher"`, `email: string | null`. Gateway получает роль и email
из проверенного подписанного LTI контекста своей регистрации и связывает email с
исходной сессией. Bridge доверяет этому private контексту только за прежним service
bearer. Публичные query/body поля, произвольный `email_verified` и role overrides
не добавляются в этот протокол.

Email уже должен быть canonical lowercase ASCII mailbox без пробелов/управляющих
символов: до 254 символов, local part до 64 без начальной/конечной или двойной точки,
домен минимум из двух DNS labels до 63 символов. Bridge адрес не нормализует и
отклоняет неверный формат с 400; `+alias` остаётся отдельным адресом. Gateway передаёт
`null`, если signed email отсутствует или не прошёл его проверку доверия.

Одна private policy `administratorEmail` задаёт такой же canonical адрес либо
`null` (по умолчанию). Его точное совпадение с подтверждённым session email выдаёт
global native Administrator **при любой из двух Moodle ролей** через существующий
administrator SQL/audit механизм. Конкретный адрес человека не встроен в код или
пример. Для остальных Teacher штатные `insertCoursePermissionsByUserUid` и
`insertCourseInstancePermissions` обеспечивают `Editor` курса и `Student Data Editor`
экземпляра; новые Owner/staff-management права и global admin им не выдаются.
Student с другим email новых staff/admin прав не получает.

До API, способного создать пользователя, проверяется existing UID; возвращённые
native ID и UID должны совпасть с исходными. Проверяются фактические записанные
permissions, audit actor — тот же проверенный native user ID. Grant выполняется
в той же native транзакции после membership/access guards. Штатные API только
повышают права; прежние Owner/admin/другие роли при следующем входе не отзываются.
Email не меняет issuer/client/deployment/subject UID и не объединяет учётные записи.

Ответ остаётся прежним из шести полей: `schemaVersion`, `userUid`, `instance`,
`courseKey`, `enrolled`, `path`; роль и email не отражаются. Успешные native вход,
grant и список курса не подтверждают grading candidate, OCI или проверку всех задач.
`login-only` не превращает импортированный private candidate в production grading
delivery. Handler tests с изолированными native boundaries не заменяют настоящий
Moodle/DB/UI smoke и проверку реальных audit records.

`GET /internal/gateway/work-results` accepts exactly userUid, instance, deliveryHash
and workId query parameters. This reads an ordinary, unlabelled manifest work without
a defense assignment slot. Joined enrollment and native Student publishing/assessment
access resolver authorize the read. The resolver always uses ordinary Student roles;
there is no staff override. Modern individual assessments are supported; other access
models fail closed. `schemas/gateway-work-results.schema.json` has the same scoped
per-slot result core v2, without assignmentId/version, plus native current attempt
`scoreGiven` (points) and `scoreMaximum` (max_points). These preserve declared weighted
grades; Gateway must not infer aggregate weights from question counts. An unattempted
work has state:not-started, null attempt/aggregate values and empty slots; completion
requiredCount/atLeast remains bound to delivery. Started results contain exactly one
selected instance_question per slot from the captured native assessment instance. Reads perform no enrollment/label writes.

`GET /internal/gateway/work-launch` uses the same scoped query. It returns only
workId, userUid, instance, deliveryHash and a native server-derived assessment path.
Ordinary work uses the Student resolver above. A label-managed defense additionally
requires its current journal work/delivery and actual native label. Numeric native IDs,
paths and privileges are never accepted from the caller.

The gateway Compose overlay requires explicit PL_GATEWAY_IMAGE and overrides the base
command with the bridge wrapper. Use a reviewed versioned local tag for builds, or a
published pinned digest with `--no-build` for deployment. It sets production mode and
adds no public listener ports. Config and consumed delivery structures are closed;
ambiguous delivery/instance bindings are rejected at startup. Canonical JSON emits
Unicode-scalar sorted key/value text directly, including numeric-looking keys.

New assignment versions, including same-work regrants, record activation with
PostgreSQL clock_timestamp() after the native ACL reconciliation and lock wait.
Earlier attempts are excluded even if a transaction began before the prior grant.
Duplicate retries retain the committed activation time and reconcile label drift.
The process rejects NODE_ENV other than production, devMode true, or hasShib false
before database initialization or listener startup.

## Явный bootstrap единственного администратора

`PUT /internal/gateway/administrator` принимает только `{userUid}` и сервисный
bearer. `administratorUid` в private bridge config по умолчанию null.
Разрешён только exact Gateway UID владельца; пользователя сначала создаёт
проверенный handoff в native PL. Сервер ищет actual user ID и создаёт
`administrators` запись с native audit, используя тот же pinned table contract,
что native administrator UI. Повторный вызов не создаёт дубликат и не добавляет
новую audit запись. Ответ содержит schemaVersion1, тот же userUid,
administrator=true и единственный путь `/pl/administrator/courses`.

Публичный proxy не публикует этот endpoint. Права полные, на всю платформу,
по явному решению пользователя; Moodle Instructor сам по себе их не даёт.
Это исключение из прежнего ограничения teacher-only Gateway; обычные teachers
по-прежнему не получают native staff/admin автоматически.

## Позиции и native выбор: версия2

Platform2.0.0 принимает только native delivery2: work.slots с полным набором
candidates, completion required-slot-completion/per-slot-results-v2. Bridge
сверяет каждую native alternative group по точному набору кандидатов. Random
требует number_choose1; singleton fixed допускает штатный NULL либо1. Выбор
подмножества зоны не поддерживается. Проверяются также лишние/неполные группы.

Результаты читаются из instance_questions захваченного assessment_instance_id,
включая обычные singleton позиции. `started` содержит ровно один выбранный
вопрос каждой позиции и currentAttempt.id/number. Пропавший, чужой, множественный
или принадлежащий другой попытке выбор отклоняется. `not-started` возвращает
null attempt и пустые slots: completedRequired0, requiredCount/atLeast из delivery.
Совершенный результат требует complete, score1, points=maxPoints>0. Не выбранные
альтернативы не выдаются как пропущенные и не увеличивают знаменатель.
