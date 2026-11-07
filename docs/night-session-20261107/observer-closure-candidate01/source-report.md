# Runtime RED round1: подтверждённый diagnostic closure конфликт

**CONTROL_CANDIDATE_ONLY; LIVE3495e5c HOLD; actual candidate NOT_RUN.** Прочитаны все10 raw merged outputs и metadata, capture-summary, outer.log/outer.json и results единственного N0 quota capture01. Calls01..09 exit0;02..09 output пуст,10exit1/445B/no timeout/no output_limit. Summary1method/1ERROR,10calls/0capture_errors; source-after349exact. Ни compound suite отказ, ни quota allocation branch не выдаются за прямую причину.

## Causal chain, подтверждённая actual и JDK25

Call10 передаёт существующий `--add-opens org.prairielearn.feedback/org.prairielearn.feedback.internal=ALL-UNNAMED` и `-Dfeedback.guard.diagnostic=quota`. Прямой stderr: `SecurityException: Observer internal package is exposed` в `RuntimeIdentity.observerClosure:260`, bootstrap:66, adapter.main:445. Bootstrap вызывает closure до чтения параметров/State bind/leaf. Поэтому этот quota job не достиг настоящей проверки allocation.

Первичный [JDK25 contract](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/lang/Module.html#isExported(java.lang.String,java.lang.Module)) получен N0 и прочитан как `control/N0/jdk25-module-effective-export-primary.json`: открытие пакета определённому модулю делает `isExported(package,thatModule)` истинным во время исполнения. Это не добавляет `exports` в ModuleDescriptor. Собственный JDK25src.zip локально отсутствует; автор не делал network/JVM probe и не подменял primary spec своей утилитой.

В exact source есть два безусловных effective-export refusal для internal: первый к system unnamed, второй ко всем foreign viewers. Первый уже истинен из фактического add-opens и JDK25 контракта, независимо от того, что fixture допустила это **только в diagnostic copy** через `_once expectedInternalOpen=false→true`. Второй дал бы следующий отказ тому же unnamed viewer, даже если поправить только первый. Это подтверждённый predicate conflict, а не исключённый ранее self-viewer: `viewers.remove(observer)` уже есть и остаётся.

Actual temporary diagnostic source/class trees очищены штатно и в capture не копировались. Прочитан immutable snapshot `test_feedback_state_guards.py`: `diagnostic_module()` меняет точный local expectedInternalOpen anchor один раз, State capture и helper; argv04 подтверждает именно diagnostic RuntimeIdentity source path. Сгенерированный temp файл не называется сохранённым byte receipt. Для выявленной причины достаточно фактического opens + primary contract + текущего безусловного predicate; его истинность не зависит от реконструкции удалённого файла.

## Только минимальный candidate

В control before/candidate сохранён ровно `RuntimeIdentity.java`. Оба `isExported` сопоставляются с **тем же** expectedOpen, который уже используется для `isOpen`:

- first unnamed check: `isExported(internal,unnamed) != expectedInternalOpen`;
- viewer check: `isExported(internal,viewer) != (expectedInternalOpen && viewer==unnamed)`.

Exact `_once` anchor `    boolean expectedInternalOpen = false;` сохранён буквально и ровно один раз; production не получает property/env bypass. Источники harness/assertions/flags/quotas не меняются, никакого нового opens не добавлено. Private method/fields/public API остались прежними.

| Ветка | Effective opens expectation | Effective export expectation | Эквивалентность |
| --- | --- | --- | --- |
| Production,E=false | false для всех foreign viewers | false | `x != false` равно прежнему `x`: обе refusal проверки буквально эквивалентны. |
| Diagnostic,E=true,V=unnamed | true, уже существующий accepted own-module opens | true по JDK contract | Учитывает ровно тот же runtime доступ, не требует нового descriptor export. |
| Diagnostic,E=true,V≠unnamed | false | false | `x != (true&&false)` равно прежнему `x`; все foreign guards прежние. |

Descriptor guards named/name/layer/requires/exports1/public package/unqualified/uses/provides/opens.empty не изменены. Public observer package по-прежнему не open ни одному foreign viewer; self viewer исключён как раньше. Разрешение конкретного diagnostic opens не расширяется на JUnit engine/launcher/commons или named modules.

## Почему это не объясняет обычные State failures

Non-diagnostic cases не получают ни true substitution, ни add-opens. Их expectedOpen=false и refusal logic после candidate остаётся математически прежней. Более того, actual State suite единственный PASS `test_stale_projection_schema_guard_and_origin_refuse_before_junit` проверил3требуемые schema/guard/trusted-root причины в captured refusals. По main source эти отказы возникают после bootstrap/RuntimeIdentity.bind и Gate.bind: production closure уже проходил в этих jobs. Поэтому blanket closure explanation для normal output_limit/incomplete reports неверно.

N0 отдельно назначил normal capture02 — один existing `test_hostile_records_are_bounded_without_user_code`, без diagnostic mode,1job/5leaves/≤10JVM на том же immutable5e5c. Его inner/request/manifest уже подготовлены в sibling normal-capture02 и переданы независимому peer. До actual normal raw причина normal failures остаётся **UNRESOLVED**, live source **HOLD**. Никакой worker/method/BCI/guard fix из догадки не предлагается.

## Предлагаемый affected subset, не новая очередь

Exact список в affected-subset.proposal.json. Helper непосредственно компилируется в production bootstrap/observer-strict и current02 initializer-probe/current10 diagnostic module:4known affected compiler units с прежними flags/caps. Остальные current sources/CP не меняются. API/upstream unit не ссылается на RuntimeIdentity; reuse после нового bootstrap требует отдельного peer/N0 ABI/dependency binding, автоматического PASS нет.

Первый runtime после accepted candidate/N0 applyGO — тот же existing quota method,1job/≤10JVM, с прежними assertions/argv/limits и при необходимости тем же approved bounded capture, привязанным к новому source root. Остальные4existing diagnostic jobs тоже зависят от expectedOpen variant, но не заказываются новой автоматической партией: N0 объединяет их с actual normal cause/remaining. Whole11/authority/boundary этим control не запускаются. Ранее обязательные consumer/image/full385/retirement gates сохраняются раздельно.

Лимиты, новые tests/runners/opens0, собственные imports/checks/JVM/network0. Перед live apply нужен другой peer, normal raw и отдельный N0 GO/new coherent map. Исходные8contexts Sol/high Standard и первоначальное начало сохранены в admission.json; автор свою причину/дельту независимо не принимает.
