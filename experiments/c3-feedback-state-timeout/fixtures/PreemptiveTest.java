import org.junit.jupiter.api.*;
import org.junit.jupiter.params.*;
import org.junit.jupiter.params.provider.*;
import org.junit.jupiter.api.parallel.*;
import org.junit.jupiter.api.function.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.jupiter.api.Assertions.*;
public class PreemptiveTest {
  static final Duration LIMIT = Duration.ofSeconds(3);
  static void demand(boolean condition) {
    if (!condition)
      throw new AssertionError("control");
  }
  @Test
  void sevenOverloads() throws Throwable {
    AtomicInteger calls = new AtomicInteger(), messages = new AtomicInteger(),
                  factories = new AtomicInteger();
    Executable executable = () -> calls.incrementAndGet();
    Object identity = new Object();
    ThrowingSupplier<Object> supplier = () -> {
      calls.incrementAndGet();
      return identity;
    };
    java.util.function.Supplier<String> message = () -> {
      messages.incrementAndGet();
      return "lazy";
    };
    Assertions.TimeoutFailureFactory<IllegalStateException> factory =
        (duration, m, cause, thread) -> {
      factories.incrementAndGet();
      return new IllegalStateException("factory");
    };
    assertTimeoutPreemptively(LIMIT, executable);
    assertTimeoutPreemptively(LIMIT, executable, "msg");
    assertTimeoutPreemptively(LIMIT, executable, message);
    demand(assertTimeoutPreemptively(LIMIT, supplier) == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, "msg") == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, message) == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, message, factory) == identity);
    assertEquals(7, calls.get());
    assertEquals(0, messages.get());
    assertEquals(0, factories.get());
    RuntimeException thrown = new RuntimeException("same");
    try {
      assertTimeoutPreemptively(LIMIT, (Executable) () -> { throw thrown; });
      throw new AssertionError();
    } catch (RuntimeException caught) {
      demand(caught == thrown);
    }
    try {
      assertTimeoutPreemptively(LIMIT, (ThrowingSupplier<Object>) () -> { throw thrown; });
      throw new AssertionError();
    } catch (RuntimeException caught) {
      demand(caught == thrown);
    }
    try {
      assertTimeoutPreemptively(LIMIT, () -> { assertEquals(8, 9); });
      throw new AssertionError();
    } catch (org.opentest4j.AssertionFailedError expected) {
    }
  }
  @Test
  void invalidArguments() {
    for (Duration duration : new Duration[] {null, Duration.ofSeconds(Long.MAX_VALUE)}) {
      AtomicInteger calls = new AtomicInteger();
      try {
        assertTimeoutPreemptively(duration, (Executable) () -> calls.incrementAndGet());
        throw new AssertionError();
      } catch (NullPointerException | ArithmeticException expected) {
      }
      demand(calls.get() <= 1);
    }
    try {
      assertTimeoutPreemptively(LIMIT, (Executable) null);
      throw new AssertionError();
    } catch (NullPointerException expected) {
    }
    try {
      assertTimeoutPreemptively(LIMIT, (ThrowingSupplier<Object>) null);
      throw new AssertionError();
    } catch (NullPointerException expected) {
    }
  }
  @Test
  void customFactory() throws Exception {
    AtomicInteger messages = new AtomicInteger(), factories = new AtomicInteger();
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1),
                   done = new CountDownLatch(1);
    IllegalStateException same = new IllegalStateException("same factory error");
    try {
      assertTimeoutPreemptively(Duration.ofMillis(250),
          (ThrowingSupplier<Object>) ()
              -> {
            entered.countDown();
            try {
              release.await(2, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
            } finally {
              done.countDown();
            }
            return null;
          },
          ()
              -> {
            messages.incrementAndGet();
            return "lazy factory";
          },
          (duration, message, cause, thread) -> {
            factories.incrementAndGet();
            demand(entered.getCount() == 0);
            demand(thread != null);
            demand(cause != null);
            demand(message.get().equals("lazy factory"));
            return same;
          });
      throw new AssertionError();
    } catch (IllegalStateException actual) {
      demand(actual == same);
    } finally {
      release.countDown();
      demand(done.await(2, TimeUnit.SECONDS));
    }
    assertEquals(1, messages.get());
    assertEquals(1, factories.get());
  }
  @Test
  void parentRestore() {
    assertEquals(77, 77);
    assertTimeoutPreemptively(LIMIT, () -> { assertEquals(78, 78); });
    assertEquals(79, 79);
  }
  static final CyclicBarrier PARAMETER_BARRIER = new CyclicBarrier(2);
  @ParameterizedTest(name = "строка {0}")
  @ValueSource(ints = {101, 202})
  @Execution(ExecutionMode.CONCURRENT)
  void parameter(int value) {
    assertTimeoutPreemptively(LIMIT, () -> {
      PARAMETER_BARRIER.await(2, TimeUnit.SECONDS);
      assertEquals(value, value);
    });
    assertEquals(value + 1, value + 1);
  }
  @TestFactory
  List<DynamicTest> dynamic() {
    return List.of(DynamicTest.dynamicTest("dynamic303", () -> {
      assertTimeoutPreemptively(LIMIT, () -> { assertEquals(303, 303); });
    }), DynamicTest.dynamicTest("dynamic404", () -> {
      assertTimeoutPreemptively(LIMIT, () -> { assertEquals(404, 404); });
    }));
  }
  @Test
  void nested() {
    assertTimeoutPreemptively(LIMIT, () -> {
      assertEquals(501, 501);
      assertTimeoutPreemptively(LIMIT, () -> { assertEquals(502, 502); });
      assertEquals(503, 503);
    });
  }
  static void deep(int n) {
    if (n == 0) {
      assertEquals(600, 600);
      return;
    }
    assertTimeoutPreemptively(LIMIT, () -> deep(n - 1));
  }
  @Test
  void depthLimit() {
    deep(5);
  }
  @Test
  void lateRevoke() throws Exception {
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1),
                   done = new CountDownLatch(1);
    try {
      try {
        assertTimeoutPreemptively(Duration.ofMillis(250), () -> {
          assertEquals(701, 701);
          entered.countDown();
          while (release.getCount() != 0) {
            try {
              release.await(2, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
            }
          }
          try {
            assertEquals(702, 702);
          } finally {
            done.countDown();
          }
        });
        throw new AssertionError();
      } catch (org.opentest4j.AssertionFailedError expected) {
        demand(entered.getCount() == 0);
      }
      assertEquals(703, 703);
    } finally {
      release.countDown();
      demand(done.await(2, TimeUnit.SECONDS));
    }
    assertEquals(704, 704);
  }
  @Test
  void ancestorRevoke() throws Exception {
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1),
                   innerDone = new CountDownLatch(1), outerDone = new CountDownLatch(1);
    try {
      try {
        assertTimeoutPreemptively(Duration.ofMillis(250), () -> {
          try {
            try {
              assertTimeoutPreemptively(LIMIT, () -> {
                assertEquals(811, 811);
                entered.countDown();
                while (release.getCount() != 0) try {
                    release.await(2, TimeUnit.SECONDS);
                  } catch (InterruptedException ignored) {
                  }
                try {
                  assertEquals(812, 812);
                } finally {
                  innerDone.countDown();
                }
              });
            } catch (Throwable expected) {
              if (!(expected instanceof InterruptedException))
                throw expected;
            }
            assertEquals(813, 813);
          } finally {
            outerDone.countDown();
          }
        });
        throw new AssertionError();
      } catch (org.opentest4j.AssertionFailedError expected) {
        demand(entered.getCount() == 0);
      }
      assertEquals(814, 814);
    } finally {
      release.countDown();
      demand(innerDone.await(2, TimeUnit.SECONDS));
      demand(outerDone.await(2, TimeUnit.SECONDS));
    }
  }
  @Test
  void workerDenied() throws Throwable {
    assertTimeoutPreemptively(LIMIT, () -> {
      assertEquals(801, 801);
      Student.controls();
      Student.facade();
      Student.reenter();
      Student.foreign();
      Thread child = new Thread(TrustedHelper::check);
      child.start();
      child.join();
      ExecutorService executor = Executors.newSingleThreadExecutor();
      try {
        executor.submit(TrustedHelper::check).get(2, TimeUnit.SECONDS);
      } finally {
        executor.shutdownNow();
      }
      assertEquals(802, 802);
    });
  }
}
