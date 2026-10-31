# Конечный эксперимент C3: State и preemptive timeout

Этот отдельный срез продолжает frozen F0 v2 `418e22edeb13ddc7ef8bf14cbe3e5cb1b726dd71` по принятой адресной дельте `c3-state-timeout-delta-report.md`. Product integration, полный compiled census 135 источников и полное решение 37 остаются HOLD. Предыдущий experiments-срез и production-файлы не изменяются.

`check.py` запускает только S1–S4/T1–T4/I1: actual D1 Book и disposable publisher defect, машинно допущенные record-проекции, исходные семь JUnit overloads, настоящий Jupiter UID, отзыв grant, предел глубины, immutable pending output и фактический decoder/projection/scorer. Это не новый runner: `run.py` компилирует исходный PlatformJUnitAdapter с прежними четырьмя observer hooks и использует единственный pinned JUnit на module-path.

```bash
XDG_CACHE_HOME=/home/tolya/Java/.cache/codex-tools GRADLE_USER_HOME=/home/tolya/Java/.cache/codex-tools/gradle JAVA_HOME=/usr/lib/jvm/java-25-openjdk PATH=/usr/lib/jvm/java-25-openjdk/bin:$PATH python experiments/c3-feedback-state-timeout/check.py
```

Каждый child имеет timeout 40 секунд и конечный terminal receipt. Источники/compiled bytes, argv, env, timings и outcomes сохраняются вне Git в `refactoring-execution/c3-state-timeout-*`. Два diagnostic режима компилируют дополнительные классы из `diagnostics`: latch/capture-паузы перед commit/end и закрытые one-use/stale/foreign-caller controls. Они не входят в обычный candidate module; у candidate нет тестовых hooks или открытого grant API. Различие modes фиксируется в receipt и compiled hashes.

Observer читает только class-identity admitted record через проверенный GETFIELD bridge. Остальные объекты остаются incomplete; accessor/toString/student List traversal не используются. Квоты сохраняются: 32768 payload bytes, 256 items, глубина 6, 64 checks, 2048 UTF-16 units на render. Учёт allocation относится к соответствующим copy/node/bridge statements и не является измерением полного JVM heap. Ошибка admission/observer не превращается в student0.

Полный JUnit/Platform suite, прежние шесть F0 groups, installed copies, OCI, portal и production pins здесь не запускаются и не меняются. Пакет требует независимой проверки exact implementation другим Sol/high.
