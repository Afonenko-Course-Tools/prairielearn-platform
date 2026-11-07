import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
  static final AtomicInteger calls = new AtomicInteger();
  static void diagnostic(String method, Executable callback) throws Throwable {
    Class<?> probe = Class.forName("org.prairielearn.feedback.internal.GuardDiagnostics");
    var target = probe.getDeclaredMethod(method, Executable.class);
    target.setAccessible(true);
    try { target.invoke(null, callback); }
    catch (java.lang.reflect.InvocationTargetException failure) { throw failure.getCause(); }
  }
  @Test void grants() throws Throwable {
    Executable denied = () -> { calls.incrementAndGet(); assertEquals(990, 990); };
    diagnostic("install", denied);
    assertTimeoutPreemptively(Duration.ofSeconds(3), (Executable) () -> {
      assertEquals(989, 989);
      diagnostic("activeReplay", denied);
      diagnostic("direct", denied);
      diagnostic("foreign", denied);
      assertEquals(993, 993);
    });
    diagnostic("revokedReplay", denied);
    assertEquals(6, calls.get());
    assertEquals(995, 995);
  }
}
