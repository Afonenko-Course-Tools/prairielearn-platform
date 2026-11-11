# Целые ручные баллы

Community fork поддерживает явную политику в `infoCourse.json`:

```json
{"options": {"integerManualPoints": true}}
```

Отсутствующее поле или `false` сохраняет штатную дробную оценку PrairieLearn.
Это расширение fork, а не опция официального upstream. Экспортёр курса
поддерживает соответствующую декларацию `prairielearn.delivery.course.options`;
его overlay сохраняет официальные vendored schemas без изменения.

При включении assessment/question maxima и manual maxima должны быть
неотрицательными безопасными целыми числами. Ручной результат должен быть целым
в пределах `0..max_manual_points`. Сервер проверяет итог после вычисления
points, percentages, total points и rubric в той же native транзакции до
сохранения grading job. Отказ откатывает также rubric grading. Таблица,
CSV upload и индивидуальная проверка используют общий native backend.

Основная форма ручной проверки использует баллы и целочисленный ввод с
границами. Дробный процент нельзя использовать для обхода серверной проверки:
например, 50% от manual max=2 даёт допустимый 1, а 25% даёт запрещённый 0.5.
Rubric adjustment имеет целый шаг; итог rubric также проверяется сервером.
Поле manual points в таблицах ограничено теми же step/min/max.

При включённой политике пользовательское представление question/assessment
points округляется до ближайшего целого: например, `8/3` отображается как `3`.
Это действует в student overview, question sidebar (включая AJAX refresh),
instructor instance table и manual grading UI. Невключённые курсы сохраняют
штатное отображение. Ручное поле ввода проверяет целочисленный результат,
а не округляет введённую дробь.

Автоматически заработанные partial points, общий сохранённый результат и
нормализованные score/percentage остаются точными и могут быть дробными.
Например, auto max=8 и score=1/3 сохраняют `8/3` automatic points. Ручная
проверка без явного редактирования automatic points не отправляет их обратно
из формы: скрытое округлённое поле не перезаписывает первичный результат.
Backend aggregate, CSV/gradebook exports и выбранный транспорт оценки не
округляются этой политикой. Отображаемый assessment total округляется от точной
суммы, поэтому может отличаться от суммы отдельно округлённых question points.
Пересчёт исторических результатов не выполняется.

`images/prairielearn/patch-integer-manual-points.py` и
`images/prairielearn/patch-integer-point-display.py` проверяют точные anchors
закреплённого upstream до любой записи. Dockerfile сначала применяет эту правку
и выполняет настоящий `npm run build` (strict TypeScript, server copy и
compiled browser assets), затем применяет существующие src/dist runtime hooks.
Это необходимо для React hydration: правки только серверного `dist` недостаточно.

Проверки: `node tests/integer-manual-points.test.mjs` и
`python -m unittest discover -s tests -p test_integer_manual_points.py`.
Фактическая интеграционная приёмка требует отдельного synthetic native course:
0/max save/reopen, fractional/negative/above-max backend rejection без изменения
результата, процентный и rubric маршруты, aggregate и нормализованный passback.
