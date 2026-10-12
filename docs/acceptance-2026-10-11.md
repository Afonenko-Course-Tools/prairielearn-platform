# Приёмка серверного пилота 11 октября 2026

Проверена отдельная Ubuntu 26.04.1 LTS VM на Proxmox: 4 vCPU, 8 GiB RAM,
60 GiB disk. Настоящий Moodle учреждения недоступен; источником подписанных
LTI 1.3 launches и получателем AGS был локальный Moodle mock на ноутбуке.
HTTPS проверялся с доверенным CA, без отключения TLS verification.
Учётные данные, приватные receipts, state и roster находятся вне Git.

## Что проверено

| Механизм | Фактический результат |
|---|---|
| Общая регистрация | Один Moodle курс и один LTI client/deployment, три элемента: Java lab, Java defense, System-Practice lab |
| Автоматическое зачисление | Два Student пользователя входят в оба native курса; одна native identity на человека, два enrollment |
| Изоляция | Student admin API/native admin и чужие assessment instances запрещены |
| Преподаватель | Явно разрешённая synthetic identity открывает штатную `/pl/administrator/courses`; один Instructor claim недостаточен |
| Java lab | Actual Student editor submissions: starter 0,25; reference 1; выполняется настоящий JDK 25 |
| Java defense | Назначение активируется через Gateway; штатный Exam start; implementation, test-design/mutation и experiment references получили 1 каждый |
| Fish lab | Actual Student editor submissions: starter 0, wrong 0,5, syntax failure, timeout, unsafe UTF-8, reference 1 |
| AGS | Самостоятельная отправка durable outbox в три отдельных Moodle lineitem; readonly readback: Java lab 1/1, defense 3/3, System lab 1/1 |
| Частичное обновление | Обновляется только System snapshot/binding/native path; Java path неизменен, все существовавшие submission scores и enrollments идентичны до/после |
| Нагрузка | 10 одновременных synthetic Students: 5 Java и 5 System, все reference submissions получили 1; максимум 2 grader containers, минимум 4,57 GiB доступной RAM VM |
| Reboot | После смены boot ID сохранились native data, оба Gateway session scope, enrollment, назначение defense, teacher admin и AGS results; systemd и guest agent активны |
| Ansible | Повторный полный apply: 27 ok, 0 changed, 0 failed; отдельный deployment mode не запускает APT bootstrap |

Оценки создавались Student HTTP forms в PrairieLearn. SQL использовался только
для чтения native identity/status/persistence; тесты не записывали оценки напрямую
и не отправляли mock AGS scores вместо Gateway.

## Проверки исходников

- Platform: 174 Python tests, 42 optional checks skipped; native Node bridge,
  cookie guards и fail-closed grader patch checks прошли отдельно.
- Gateway: 115 passed, 1 optional fixture integration skipped; actual server
  integration выше проверена отдельными HTTP probes.
- Exporter: 41 Deno tests passed; регрессии non-Java complete delivery и EXDEV.
- System-Practice: student/full по 22 страницы, 53 QRC цели, 248 resolved links,
  0 deferred links в итоговом каталоге; whole-package ZIP installation проверена.
- Финальный fish container receipt: complete coverage пяти сценариев
  starter/reference/wrong/invalid/timeout. Дополнительный shared-deadline тест
  сначала воспроизвёл ошибку, затем подтвердил student-timeout; независимое ревью
  приняло исправление.

## Точные diagnostic artifacts

Это **config image IDs**, а не published registry manifest digests:

| Image | Config ID |
|---|---|
| PL Community + bridge | `sha256:6101d5842bc9c07b110cc9f99d63f402c32dceb11bf7bab15798ff16507d40bb` |
| Gateway | `sha256:49af18ab2ca07a0397d3bdedb7d5e2d0352dfa58b64b1db27356ed1d941917b0` |
| Java 25 grader | `sha256:58f777a8c1ba296e22fe3314fe9c68a4c31ec5e4832c849ee8c671029dddf803` |
| Fish grader | `sha256:b9c818e51c44d671b8d9dc4f78bb292d2d5c6c3ba3d52a9ef3e43e33f95c24c3` |
| nginx | `sha256:43d9d8c1f8968f09df8c1aa6c136ecc617e62d64fe4c0b24c97de4eb210bd973` |

Java delivery: `3439351035a80ae3a1c93ee6c432aaae30a0799e65dd02afaf9725e77fc26d94`.
System final delivery: `c38e1cf43e8f8a43b9f016e3d35011d696afbc42ea81e050a2f3ec7b385a19bb`.
PL upstream pinned source: `92584fe426ececb84bc2d09de9975c7056c0c5f6`.
Fish dependency closure и runner hash проверены registry/receipt.

Доступ к опубликованным GHCR artifacts текущими токенами не подтверждён.
Проверка diagnostic candidates не заменяет published promotion, production
release или запуск настоящего Moodle учреждения. Новый fish profile сохраняет
`image: null`; выпуск digest и опубликованного native System artifact требует
следующего release этапа. Исходящий доступ VM к системным repositories также
требует отдельного доступного транспорта; runtime после bootstrap автономен.
