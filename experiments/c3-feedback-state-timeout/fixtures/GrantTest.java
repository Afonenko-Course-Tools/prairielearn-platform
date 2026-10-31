import org.junit.jupiter.api.*;
import java.time.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;
import org.prairielearn.feedback.PublicationControl;
public class GrantTest {
  @Test
  void oneUse() throws Exception {
    AtomicInteger calls = new AtomicInteger();
    assertTimeoutPreemptively(Duration.ofSeconds(3), () -> {
      assertEquals(989, 989);
      PublicationControl.repeated(() -> {
        calls.incrementAndGet();
        assertEquals(990, 990);
      });
      PublicationControl.direct(() -> {
        calls.incrementAndGet();
        assertEquals(992, 992);
      });
      assertEquals(993, 993);
    });
    PublicationControl.stale(() -> {
      calls.incrementAndGet();
      assertEquals(991, 991);
    });
    assertEquals(4, calls.get());
    assertEquals(995, 995);
  }
}
