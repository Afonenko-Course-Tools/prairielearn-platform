# Предварительная проверка опубликованного Java API

Локальный кандидат после 2.1.0, без опубликованного выпуска. Прежние descriptors
без `apiPrecheck` сохраняют существующий порядок. Новый optional descriptor:

```json
"apiPrecheck": {"files": ["ApiContract.java"], "entry": "ApiContract"}
```

`files` — непустое собственное подмножество `testFiles`. Остальные sources
являются обычными зависимыми JUnit-тестами. Только implementation Java;
mutation и fish не используют эту стадию. Класс проверки содержит метод:

```java
import org.prairielearn.api.PlatformApiPrecheck;
import java.lang.reflect.Modifier;
public class ApiContract {
    public static void check(PlatformApiPrecheck.Api api) throws Exception {
        api.method("Student", "answer", int.class,
            Modifier.PUBLIC | Modifier.STATIC, 0);
        api.compiles("Client", "class Client {int value=Student.answer();}", true);
    }
}
```

Это пример API синтетической проверки, не требование ко всем задачам.
Проект задаёт только опубликованные имена, сигнатуры и клиентские контракты.
Сам precheck компилируется без student classpath; статические ссылки на
student types в его Java source запрещены самой компиляцией. `api.type(name)`
загружает класс отдельным loader через `Class.forName(name, false, loader)`.
`api.method` проверяет точные параметры/return type и required/forbidden
modifier masks; возвращённый `Method` позволяет прочитать generic/throws
метаданные штатной reflection. `api.expect` даёт expected/observed диагностику.
Поиск сначала использует `getMethod`: доступный public метод может быть
унаследован. Для метаданных non-public метода самого владельца применяется
`getDeclaredMethod`. Требование «объявлен именно в этом классе» не вводится
автоматически: только явное опубликованное условие проверяется через
`api.expect(method.getDeclaringClass() == api.type("Student"), …)`.

`api.compiles(name, source, expected)` отдельно компилирует typed client с
JDK25, `-proc:none`, UTF-8 и compiled student classpath. Клиенты не попадают
в classpath друг друга. Сначала требуется успешная положительная проба;
wrong-type клиент объявляет `throws Exception`, отдельная checked-проба
использует верные типы. Каждый preflight обязательно проверяется на reference:
синтаксическая ошибка самого положительного клиента не является доказательством
неверного student API. Erased reflection не заменяет generic/checked клиентов.

Порядок выполнения: student compilation → precheck compilation/execution →
dependent compilation → JUnit. Metadata inspection не инициализирует student
классы. Проектный код не должен вызывать constructors/methods в этой стадии;
поведение проверяется последующими JUnit. В контейнере precheck выполняется
через тот же sbuser/Landlock с read-only compiled inputs, offline limits и
отдельным writable scratch. Timeout/output overflow этой trusted стадии —
инфраструктурная ошибка, а не student timeout/score 0.

Нарушение API возвращает `student-api-mismatch`, `studentCompilation=success`,
`trustedCompilation=not-run`, `apiPrecheck=failure`, `dependentExecution=not-run`,
expected/observed и причину пропуска unit-тестов, без score. Непредвиденный
отказ precheck либо dependent compiler после успешного preflight не оценивается
как поведение студента: нужно установить пробел API-контракта или дефект
trusted tests. Public verification использует собственную precheck selection.

Core объявляет `api-precheck: {files: [tests/…], entry: …}` и отдельно
`verification-api-precheck: {files: [student/…], entry: …}`. Collector разрешает
только subsets своих trusted/public sources; bytes входят в snapshot hashes.
Нативный exporter переносит нормализованный private subset в descriptor.
Добавление этих полей к старому опубликованному image не включает новый код:
нужен проверенный local candidate либо отдельно выпущенный новый digest.
