import org.junit.jupiter.api.*;
import java.util.concurrent.TimeUnit;
import java.time.Duration;
import static org.junit.jupiter.api.Assertions.*;
public class TimeoutTest {
  @Test
  @DisplayName("Timeout в текущем потоке")
  @Timeout(value = 2, threadMode = Timeout.ThreadMode.SAME_THREAD)
  void same() {
    assertEquals(12, 12);
  }
  @Test
  @DisplayName("Timeout в отдельном потоке")
  @Timeout(value = 2, threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
  void separate() {
    assertEquals(34, 34);
  }
  @Test
  @DisplayName("Истечение отдельного timeout")
  @Timeout(
      value = 50, unit = TimeUnit.MILLISECONDS, threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
  void
  expires() throws Exception {
    assertEquals(56, 56);
    Thread.sleep(1000);
  }
  @Test
  @DisplayName("Preemptive callback")
  void preemptive() {
    assertTimeoutPreemptively(Duration.ofSeconds(2), () -> { assertEquals(78, 78); });
  }
}
