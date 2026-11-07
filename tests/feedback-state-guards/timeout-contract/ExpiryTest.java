import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.assertEquals;

/** Настоящий expired leaf — trusted infrastructure на действующей границе grader. */
public class ExpiryTest {
  @Test @Timeout(value = 350, unit = TimeUnit.MILLISECONDS, threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
  void expires() throws InterruptedException {
    assertEquals(5601, 5601);
    Thread.sleep(2000);
  }
}
