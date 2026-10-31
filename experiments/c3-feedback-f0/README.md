# C3 F0: ограниченный воспроизводимый блокер JPMS service admission

Это **отдельный POC orchestration**, не новый продуктовый grader/runner и не C3 production integration. `run.py` компилирует неизменённые `PlatformJUnitAdapter.java` и official upstream из текущего runtime, отдельные fixture/student outputs, а затем вызывает тот же actual adapter main с тем же pinned JUnit jar и обычными Java runtime flags. Production grade.py, adapter, validators, profiles и installed composition не меняются.

Выбранная архитектура предполагает закрытый named observer module, `provides org.junit.jupiter.api.extension.Extension`, включение через `--module-path`/`--add-modules` и read edge к существующему JUnit на classpath. **Этот точный путь не проходит boot-layer service resolution.** Минимальный provider `Scope` реализует штатный InvocationInterceptor без своего поведения; этого достаточно для воспроизведения. Никаких opens, reflection обходов, private exploits, новых студентских API или внешних зависимостей здесь нет.

`Transform.java` — только bounded ClassFile POC для шести явно перечисленных descriptor-перегрузок в fixture. Он сохраняет descriptor, записывает post-transform BCI/line/ordinal/hash и запускает bytecode verifier. Facade — typed pass-through исходной JUnit overload. Это **не реализация observer/provenance/snapshot/consumer**. Candidate не запускается из-за module admission; static compilation/verifier нельзя считать доказательством runtime семантики или безопасности. Первоначальный черновик observer до первого запуска был удалён при минимизации блокера: он не исполнился и не квалифицирован.

В репозитории фиксируется ровно шесть F0 groups, но после конкретного F0-2 FAIL остальные не выполняются:

| Группа | Итог |
| --- | --- |
| F0-1 transform/delegate | UNKNOWN: исходный adapter выполняет2leaf/1pass/1fail; candidate не достиг JVM main/Jupiter |
| F0-2 module/mutation | FAIL: выбранный named provider + classpath service не разрешается boot layer; мутация authority ещё NOT_RUN |
| F0-3 scope/origin | UNKNOWN: NOT_RUN после F0-2 |
| F0-4 threads/timeouts | UNKNOWN: NOT_RUN после F0-2 |
| F0-5 values/consumer | UNKNOWN: NOT_RUN, M1/M2 не доказаны |
| F0-6 callbacks | UNKNOWN: NOT_RUN после F0-2 |

Actual byte fixture `"x ".repeat(5000)+"end"` равен10003ASCII/UTF-8bytes. Это только точная арифметика источника, **не** выполненный M2 control: измеренного first diff после10240 пока нет. Snapshot quota до allocation и unchanged delegate/scoring M1 также ещё NOT_RUN. Полный feedback/решение37 не принят.

## Повтор

```bash
export XDG_CACHE_HOME=/home/tolya/Java/.cache/codex-tools
export GRADLE_USER_HOME=/home/tolya/Java/.cache/codex-tools/gradle
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export PATH="$JAVA_HOME/bin:$PATH"
python experiments/c3-feedback-f0/run.py --baseline-red
python experiments/c3-feedback-f0/run.py
```

Первая команда должна завершиться exit1 на **отсутствии checks** в обычных реально выполненных assertions. Это исходный RED, не тест module admission. Вторая должна завершиться exit1 на конкретном `ResolutionException`; это конечный F0 FAIL, **не** PASS остальных invariants. Все дочерние процессы имеют timeout40s, subprocess.run дожидается их конца; при timeout он убивает и дожидается процесса. Full suite не запускается. Полные source/JDK/jar/generated-output hashes, argv, flags, stdout/stderr, timings и terminal states записываются в `X/c3-feasibility.json` (либо `c3-f0-red-receipt.json`); copied evidence лежит в указанном там `evidence_root`. X — `/home/tolya/Java/.cache/codex-tools/refactoring-execution`.

Наблюдённое сообщение JVM (фактически stdout; stderr пустой):

```text
Error occurred during initialization of boot layer
java.lang.module.ResolutionException: Module org.prairielearn.feedback provides org.junit.jupiter.api.extension.Extension but does not read a module that exports org.junit.jupiter.api.extension to org.prairielearn.feedback
```

Ожидание: boot-layer допускает observer service и запускается adapter/Jupiter. Факт: отказ до main; не получены candidate counts и ни одно значение observer. Узкий вопрос прежнему Astra — **как должен быть принят service provider named module при выбранном положении JUnit на classpath**. Самовольно менять module placement, service scheme или открывать authority ради запуска эта партия не будет.
