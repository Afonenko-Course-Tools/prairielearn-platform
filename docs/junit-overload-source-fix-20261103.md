# Три точных перегрузки JUnit: Source-кандидат

Façade `org.prairielearn.feedback.Assertions` дополнена тремя перегрузками,
встретившимися в доверенных скомпилированных тестах:

- `assertEquals(int, Integer)`;
- `assertFalse(boolean, String)`;
- `assertArrayEquals(char[], char[])`.

Каждая сохраняет exact descriptor, однократно делегирует одноимённому методу
JUnit и использует прежние `State.begin/end` для returned/threw. Cast,
unboxing и переоценка аргументов не добавлены. `Transform`, private policy,
контроль module/caller/site и прочие admission guards не изменены.
Неизвестная точная сигнатура продолжает отклоняться.

Адресный Source-контроль `test_assertion_feedback_overloads_static.py` использует
настоящие JDK25, JUnit1.14.1, Transform и production façade. Он проверяет
успешные вызовы, пять настоящих AssertionFailedError, null semantics и refusal
неизвестной boolean-array перегрузки. Это не запуск grader/OCI. Проверка
leaf feedback добавлена в существующий production suite, но в этом Source
пакете не запускалась: для неё нужен отдельный разрешённый runtime этап.

Изменение пока не влияет на выпущенные OCI или текущую поставку. Требуются
независимое review, новый image digest/registry и честная регенерация Native
provenance после первоначального развёртывания. Два результата
`exceptions-stack` с отсутствующим полным отчётом остаются OPEN: прежний
runner не сохранил exit/output, позволяющие установить причину.
