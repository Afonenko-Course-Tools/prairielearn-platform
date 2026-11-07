package org.prairielearn.feedback.internal;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.jupiter.api.function.Executable;

/** Только временная диагностическая копия модуля; пакет не экспортируется. */
final class GuardDiagnostics {
  private static final CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
  private static final AtomicBoolean claimed = new AtomicBoolean(), closed = new AtomicBoolean();
  private static volatile List<Map<String, String>> frozen;
  private static volatile String bytes;
  private static volatile State.Grant captured;
  private static volatile Executable denied;

  static void pause(String stage) {
    if (!stage.equals(System.getProperty("feedback.guard.diagnostic")) || !claimed.compareAndSet(false, true))
      return;
    entered.countDown();
    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
    while (release.getCount() != 0) {
      if (System.nanoTime() >= deadline) throw new AssertionError("diagnostic release timeout");
      try { release.await(50, TimeUnit.MILLISECONDS); } catch (InterruptedException ignored) {}
    }
  }
  static void capture(List<Map<String, String>> output) {
    if ("quota".equals(System.getProperty("feedback.guard.diagnostic"))) {
      if (output.size() != 1) throw new AssertionError("quota check count");
      var check = output.getFirst();
      if (!"<record quota before allocation>".equals(check.get("actual")))
        throw new AssertionError("record quota branch не достигнута");
      for (String key : List.of("_snapshotRecordNodes", "_snapshotRecordComponents", "_snapshotArrays",
                               "_snapshotArrayPayloadBytes"))
        if (!"0".equals(check.get(key))) throw new AssertionError("allocation до квоты: " + key);
    } else if ("array-quota".equals(System.getProperty("feedback.guard.diagnostic"))) {
      if (output.size() != 1) throw new AssertionError("array quota check count");
      var check = output.getFirst();
      if (!"<quota before array allocation>".equals(check.get("actual"))
          || !"<quota before array allocation>".equals(check.get("expected"))
          || !"threw".equals(check.get("delegated")))
        throw new AssertionError("array quota/delegate branch не достигнута");
      for (String key : List.of("_snapshotArrays", "_snapshotArrayPayloadBytes"))
        if (!"0".equals(check.get(key))) throw new AssertionError("array allocation до квоты: " + key);
    } else if (frozen == null && entered.getCount() == 0) {
      frozen = output;
      bytes = output.toString();
    }
  }
  static void assertEntered() {
    if (entered.getCount() != 0) throw new AssertionError("pause не достигнут");
  }
  static void release() { release.countDown(); }
  static void assertFrozen() {
    var snapshot = frozen;
    if (snapshot == null || !bytes.equals(snapshot.toString())) throw new AssertionError("snapshot изменён");
    try { snapshot.add(Map.of()); throw new AssertionError("mutable list"); }
    catch (UnsupportedOperationException expected) {}
    for (var check : snapshot) {
      try { check.put("actual", "changed"); throw new AssertionError("mutable map"); }
      catch (UnsupportedOperationException expected) {}
    }
    if (!bytes.equals(snapshot.toString())) throw new AssertionError("snapshot изменён после mutator");
  }
  private static State.Grant current() throws ReflectiveOperationException {
    var field = State.class.getDeclaredField("CONTEXT");
    field.setAccessible(true);
    var context = (State.Context) ((ThreadLocal<?>) field.get(null)).get();
    if (context == null || context.grant() == null) throw new AssertionError("нет actual worker grant");
    return context.grant();
  }
  private static int state(State.Grant grant) throws ReflectiveOperationException {
    var field = State.Grant.class.getDeclaredField("state");
    field.setAccessible(true);
    return field.getInt(grant);
  }
  static void install(Executable callback) { denied = callback; }
  static void activeReplay(Executable callback) throws Exception {
    captured = current();
    if (state(captured) != 1) throw new AssertionError("ожидался ACTIVE grant");
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2),
        new Timeouts.ExecutableWrapper(captured, callback));
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2),
        new Timeouts.ExecutableWrapper(captured, callback));
  }
  static void direct(Executable callback) throws Throwable {
    new Timeouts.ExecutableWrapper(current(), callback).execute();
  }
  static void foreign(Executable callback) throws Exception {
    State.Grant grant = current();
    AtomicReference<Throwable> failure = new AtomicReference<>();
    Thread thread = new Thread(() -> {
      try { new Timeouts.ExecutableWrapper(grant, callback).execute(); }
      catch (Throwable caught) { failure.set(caught); }
    });
    thread.start(); thread.join(2000);
    if (thread.isAlive() || failure.get() != null) throw new AssertionError("foreign callback", failure.get());
  }
  static void afterClosed(State.Grant grant) {
    try {
      if (grant != captured || state(grant) != 2 || !closed.compareAndSet(false, true)) return;
      // Между production deactivate(CLOSED) и Assertions finally revoke(REVOKED).
      org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2),
          new Timeouts.ExecutableWrapper(grant, denied));
    } catch (ReflectiveOperationException failure) { throw new AssertionError(failure); }
  }
  static void revokedReplay(Executable callback) throws Exception {
    if (captured == null || state(captured) != 3 || !closed.get())
      throw new AssertionError("не пройден CLOSED → REVOKED");
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2),
        new Timeouts.ExecutableWrapper(captured, callback));
  }
}
