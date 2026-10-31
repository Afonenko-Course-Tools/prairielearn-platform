# C3 finite F0 v2

Только изолированные experiments. Production grade.py, adapter/upstream sources, decoder, projection, profiles, Java courses, installed/OCI/portal не изменяются. Скрипт является конечной POC orchestration вокруг настоящего PlatformJUnitAdapter/Jupiter, а не новым product runner. Старый F0 FAIL пакет сохранён отдельно.

Используется принятая JPMS дельта: единственный exact pinned standalone JUnit на runtime module-path как automatic `org.junit.platform.console.standalone`, observer явно requires его. Нет ALL-UNNAMED/opens/runtime classpath duplicate. Студентские/доверенные outputs раздельны. Candidate adapter — временная derived copy с четырьмя hooks bind/register/start/finish; upstream остаётся неизменным. Трансформируется только fresh trusted compilation output; student classes не изменяются. Ровно шесть F0 groups, каждый child process ограничен40s, точные команды/hash/timing/terminal records сохраняются.

Закрытый observer связывает конкретные Class/loader/root/post-transform hashes и live method/descriptor/BCI, проверяет exported mutating entry points и engine scope. Jupiter interceptor использует текущий UID в ThreadLocal без inheritance. Caller path проверяется до module-owned invocation anchor, а не по Throwable. Hidden lambda wrapper допускается только рядом с actual hashed trusted implementation frame; helper reentry через Student/foreign Class не получает authority. Оригинальная типизированная JUnit overload вызывается ровно один раз. Callback wrappers наблюдают фактический callback, не assertion Throwable fields; message supplier вызывает только JUnit. Нет произвольного toString/getters/iterator/field traversal.

Safe snapshots ограничены32768bytes/256items/depth6/checks64 **до дополнительных копий**; scan ограничен размером допущенного snapshot. Overflow сохраняет delegate/verdict/score и отмечает неполноту. Audit-поля `_thread`, `_bci`, `_snapshotArrayPayloadBytes`, `_snapshotArrays` учитывают payload/copy statements (не VM heap headers), остаются private F0 evidence и исключаются из публичной проекции. `consumer.py` — candidate checks validation/projection extension, исполняющая настоящие неизменённые canonical JUnit decoder, student_result и grader._score; несколько checks остаются внутри одного scored leaf. Это proof producer→canonical boundary, не включённая production ABI.

Конечные обязательные результаты не подменяются наличием APIs/exit0. `@Timeout` SAME/SEPARATE проверяются реально. Preemptive worker inner assertions **ещё не имеют authenticated observer scope**, без автоматического наследования или новой propagation схемы; это UNKNOWN/HOLD, не полный F0 PASS. Actual D1 Book использует trusted record State: immutable List renderer не раскрывает его компоненты. Такой обязательный ранний value shape остаётся incomplete/HOLD; Java/педагогический договор не меняется.

Запуск из Platform:

```bash
export XDG_CACHE_HOME=/home/tolya/Java/.cache/codex-tools
export GRADLE_USER_HOME=/home/tolya/Java/.cache/codex-tools/gradle
export JAVA_HOME=/usr/lib/jvm/java-25-openjdk
export PATH="$JAVA_HOME/bin:$PATH"
python experiments/c3-feedback-f0-v2/run.py
```

Итоги записываются только в `X/c3-f0-v2-*`; result UNKNOWN даёт exit2, FAIL — exit1, полный PASS — exit0. Exit2 означает завершённую finite партию с открытыми gates, не принятие37. `--group N` адресно повторяет одну из тех же6групп. `--capture-disabled --group 1` воспроизводит RED отсутствующих checks. Текущий output receipt mutable; для независимого входа координатор получает frozen copy с SHA manifest. Все источники из D1/author archive читаются по точным paths/hashes, не меняются. Full descriptor/type/thread census всего курса сюда не входит.
