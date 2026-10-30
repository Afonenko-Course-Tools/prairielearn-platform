package org.prairielearn.feedback.internal;
import java.time.Duration;
import org.junit.jupiter.api.function.Executable;
/** Только diagnostic mode: доступ к собственному закрытому module для finite negative controls. */
public final class GrantProbe {
  private static State.Grant captured;
  private static State.Grant current() throws Exception {
    var field = State.class.getDeclaredField("CONTEXT");
    field.setAccessible(true);
    State.Context context = (State.Context) ((ThreadLocal<?>) field.get(null)).get();
    if (context == null || context.grant() == null)
      throw new AssertionError("нет actual worker grant");
    return context.grant();
  }
  public static void repeated(Executable callback) throws Exception {
    captured = current();
    var wrapper = new Timeouts.ExecutableWrapper(captured, callback);
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2), wrapper);
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(Duration.ofSeconds(2), wrapper);
  }
  public static void direct(Executable callback) throws Throwable {
    new Timeouts.ExecutableWrapper(current(), callback).execute();
  }
  public static void stale(Executable callback) {
    if (captured == null)
      throw new AssertionError("grant не сохранён");
    org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(
        Duration.ofSeconds(2), new Timeouts.ExecutableWrapper(captured, callback));
  }
}
