import org.junit.jupiter.api.*;
import java.time.*;
import java.util.concurrent.*;
import org.prairielearn.feedback.PublicationControl;
import static org.junit.jupiter.api.Assertions.*;
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class PublicationTest {
  static CountDownLatch done = new CountDownLatch(1);
  @Test
  @Order(1)
  void freezePending() {
    try {
      assertTimeoutPreemptively(Duration.ofMillis(250), () -> {
        try {
          assertEquals(901, 901);
        } finally {
          done.countDown();
        }
      });
      throw new AssertionError("ожидался controlled timeout");
    } catch (org.opentest4j.AssertionFailedError expected) {
      if (!PublicationControl.entered())
        throw new AssertionError("pause не достигнут");
    }
  }
  @Test
  @Order(2)
  void releaseAfterFinish() throws Exception {
    try {
      if (!PublicationControl.stable())
        throw new AssertionError("frozen output изменился");
      if (!done.await(2, TimeUnit.SECONDS))
        throw new AssertionError("callback не завершился");
      if (!PublicationControl.stable())
        throw new AssertionError("late output изменился");
      assertEquals(902, 902);
    } finally {
      PublicationControl.release();
    }
  }
  @AfterAll
  static void cleanup() throws Exception {
    PublicationControl.release();
    if (!done.await(3, TimeUnit.SECONDS))
      throw new AssertionError("cleanup callback");
  }
}
