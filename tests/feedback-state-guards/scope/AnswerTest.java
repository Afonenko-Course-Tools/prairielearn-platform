import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.function.Executable;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
  static void demand(boolean ok) { if (!ok) throw new AssertionError("контроль"); }
  static void await(CountDownLatch latch) throws InterruptedException {
    demand(latch.await(3, TimeUnit.SECONDS));
  }
  static void uninterruptible(CountDownLatch latch) {
    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
    while (latch.getCount() != 0) {
      if (System.nanoTime() >= deadline) throw new AssertionError("release timeout");
      try { latch.await(50, TimeUnit.MILLISECONDS); } catch (InterruptedException ignored) {}
    }
  }
  @Test void restore() {
    assertEquals(77, 77);
    assertTimeoutPreemptively(Duration.ofSeconds(3), () -> { assertEquals(78, 78); });
    assertEquals(79, 79);
  }
  @Test void directWorker() throws Exception {
    AtomicReference<Throwable> failure = new AtomicReference<>();
    assertEquals(801, 801);
    Thread worker = new Thread(() -> {
      try { assertEquals(899, 899); } catch (Throwable caught) { failure.set(caught); }
    });
    worker.start(); worker.join(3000);
    demand(!worker.isAlive() && failure.get() == null);
    assertEquals(802, 802);
  }
  static void deep(int n) {
    if (n == 0) { assertEquals(600, 600); return; }
    assertTimeoutPreemptively(Duration.ofSeconds(3), () -> deep(n - 1));
  }
  @Test void depth() { deep(5); }
  @Test void ancestor() throws Exception {
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1),
        innerDone = new CountDownLatch(1), outerDone = new CountDownLatch(1);
    AtomicReference<Throwable> unexpected = new AtomicReference<>();
    try {
      try {
        assertTimeoutPreemptively(Duration.ofMillis(350), (Executable) () -> {
          try {
            assertTimeoutPreemptively(Duration.ofSeconds(3), (Executable) () -> {
              try {
                assertEquals(811, 811); entered.countDown(); uninterruptible(release);
                assertEquals(812, 812);
              } finally { innerDone.countDown(); }
            });
            assertEquals(813, 813);
          } catch (Throwable caught) {
            // JUnit передаёт InterruptedException без checked throws в публичном API.
            if (!(caught instanceof InterruptedException)) unexpected.set(caught);
          }
          finally { outerDone.countDown(); }
        });
        throw new AssertionError("ожидался timeout");
      } catch (org.opentest4j.AssertionFailedError expected) { demand(entered.getCount() == 0); }
      assertEquals(814, 814);
    } finally {
      release.countDown(); await(innerDone); await(outerDone);
    }
    demand(unexpected.get() == null);
  }
}
