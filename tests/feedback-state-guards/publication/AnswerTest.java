import org.junit.jupiter.api.*;
import org.junit.jupiter.api.function.Executable;
import java.time.Duration;
import java.util.concurrent.*;
import static org.junit.jupiter.api.Assertions.*;
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class AnswerTest {
  static final CountDownLatch done = new CountDownLatch(1);
  static void diagnostic(String method) throws Exception {
    Class<?> probe = Class.forName("org.prairielearn.feedback.internal.GuardDiagnostics");
    var target = probe.getDeclaredMethod(method);
    target.setAccessible(true);
    try { target.invoke(null); }
    catch (java.lang.reflect.InvocationTargetException failure) {
      throw new AssertionError("diagnostic " + method, failure.getCause());
    }
  }
  @Test @Order(1) void freeze() throws Exception {
    try {
      assertTimeoutPreemptively(Duration.ofMillis(350), (Executable) () -> {
        try { assertEquals(901, 901); } finally { done.countDown(); }
      });
      throw new AssertionError("ожидался controlled timeout");
    } catch (org.opentest4j.AssertionFailedError expected) { diagnostic("assertEntered"); }
  }
  @Test @Order(2) void release() throws Exception {
    try {
      // Первая проверка — после finish, до освобождения producer.
      diagnostic("assertFrozen");
      diagnostic("release");
      if (!done.await(3, TimeUnit.SECONDS)) throw new AssertionError("callback не завершён");
      // done ставится после возврата из begin/end, включая live recheck.
      diagnostic("assertFrozen");
      assertEquals(902, 902);
    } finally { diagnostic("release"); }
  }
  @AfterAll static void cleanup() throws Exception {
    diagnostic("release");
    if (!done.await(3, TimeUnit.SECONDS)) throw new AssertionError("cleanup worker");
  }
}
