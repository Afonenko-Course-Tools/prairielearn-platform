import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import java.util.function.Supplier;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.function.*;
import org.opentest4j.AssertionFailedError;
import static org.junit.jupiter.api.Assertions.*;

public class AnswerTest {
  static final Duration LIMIT = Duration.ofSeconds(3);
  static void demand(boolean ok) { if (!ok) throw new AssertionError("контроль делегата"); }

  @Test void sevenOverloads() {
    AtomicInteger calls = new AtomicInteger(), messages = new AtomicInteger(), factories = new AtomicInteger();
    Executable executable = () -> {
      int call = calls.incrementAndGet();
      assertEquals(7100 + call, 7100 + call);
    };
    String identity = new String("возврат");
    ThrowingSupplier<String> supplier = () -> {
      executable.execute();
      return identity;
    };
    Supplier<String> message = () -> { messages.incrementAndGet(); return "ленивое сообщение"; };
    Assertions.TimeoutFailureFactory<IllegalStateException> factory = (duration, text, cause, thread) -> {
      factories.incrementAndGet();
      return new IllegalStateException("неожиданный timeout");
    };
    assertTimeoutPreemptively(LIMIT, executable);
    assertTimeoutPreemptively(LIMIT, executable, "сообщение");
    assertTimeoutPreemptively(LIMIT, executable, message);
    demand(assertTimeoutPreemptively(LIMIT, supplier) == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, "сообщение") == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, message) == identity);
    demand(assertTimeoutPreemptively(LIMIT, supplier, message, factory) == identity);
    assertEquals(7, calls.get());
    assertEquals(0, messages.get());
    assertEquals(0, factories.get());
    RuntimeException original = new IllegalStateException("исходный Throwable");
    try {
      assertTimeoutPreemptively(LIMIT, (Executable) () -> { throw original; });
      throw new AssertionError("Потерян Throwable executable");
    } catch (RuntimeException actual) { demand(actual == original); }
    try {
      assertTimeoutPreemptively(LIMIT, (ThrowingSupplier<String>) () -> { throw original; });
      throw new AssertionError("Потерян Throwable supplier");
    } catch (RuntimeException actual) { demand(actual == original); }
    assertEquals(7199, 7199);
  }

  @Test void invalidArguments() {
    for (Duration duration : new Duration[]{null, Duration.ofSeconds(Long.MAX_VALUE)}) {
      AtomicInteger calls = new AtomicInteger();
      try {
        assertTimeoutPreemptively(duration, (Executable) () -> { calls.incrementAndGet(); });
        throw new AssertionError("Принят некорректный duration");
      } catch (NullPointerException | ArithmeticException expected) {}
      // Прежний JUnit контракт допускает race submit до проверки duration, но не повтор callback.
      demand(calls.get() <= 1);
    }
    try {
      assertTimeoutPreemptively(LIMIT, (Executable) null);
      throw new AssertionError("Принят null executable");
    } catch (NullPointerException expected) {}
    try {
      assertTimeoutPreemptively(LIMIT, (ThrowingSupplier<String>) null);
      throw new AssertionError("Принят null supplier");
    } catch (NullPointerException expected) {}
    assertEquals(7201, 7201);
  }

  @Test void customFactory() throws Exception {
    AtomicInteger calls = new AtomicInteger(), messages = new AtomicInteger(), factories = new AtomicInteger();
    AtomicReference<Thread> worker = new AtomicReference<>();
    AtomicReference<Throwable> originalCause = new AtomicReference<>();
    CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), done = new CountDownLatch(1);
    IllegalStateException identity = new IllegalStateException("исходный результат factory");
    Duration duration = Duration.ofMillis(350);
    try {
      assertTimeoutPreemptively(duration, (ThrowingSupplier<Object>) () -> {
        calls.incrementAndGet(); worker.set(Thread.currentThread()); entered.countDown();
        try { release.await(3, TimeUnit.SECONDS); }
        catch (InterruptedException expected) {}
        finally { done.countDown(); }
        return null;
      }, () -> { messages.incrementAndGet(); return "ленивая factory"; },
      (actualDuration, message, cause, thread) -> {
        factories.incrementAndGet();
        demand(actualDuration.equals(duration) && entered.getCount() == 0);
        demand(thread != null && thread == worker.get() && cause != null);
        demand(cause.getClass().getModule() == Assertions.class.getModule());
        originalCause.set(cause); identity.initCause(cause);
        demand(message.get().equals("ленивая factory"));
        return identity;
      });
      throw new AssertionError("Factory timeout не произошёл");
    } catch (IllegalStateException actual) {
      demand(actual == identity && actual.getCause() == originalCause.get());
    } finally {
      release.countDown(); demand(done.await(3, TimeUnit.SECONDS));
    }
    assertEquals(1, calls.get());
    assertEquals(1, messages.get());
    assertEquals(1, factories.get());
    assertEquals(7301, 7301);
  }

  @Test void callbackDelegates() {
    AtomicInteger calls = new AtomicInteger(), messages = new AtomicInteger();
    RuntimeException original = new IllegalStateException("исходный callback Throwable");
    demand(assertThrows(RuntimeException.class, () -> { calls.incrementAndGet(); throw original; }) == original);
    try {
      assertThrows(IllegalArgumentException.class, () -> { calls.incrementAndGet(); throw original; },
          () -> { messages.incrementAndGet(); return "ленивый wrong-type"; });
      throw new AssertionError("Wrong-type не отклонён");
    } catch (AssertionFailedError expected) {}
    try {
      assertThrows(RuntimeException.class, () -> { calls.incrementAndGet(); });
      throw new AssertionError("No-throw не отклонён");
    } catch (AssertionFailedError expected) {}
    Object identity = new Object();
    demand(assertDoesNotThrow((ThrowingSupplier<Object>) () -> { calls.incrementAndGet(); return identity; }) == identity);
    assertDoesNotThrow((Executable) () -> { calls.incrementAndGet(); });
    try {
      assertDoesNotThrow((Executable) () -> { calls.incrementAndGet(); throw original; });
      throw new AssertionError("Неожиданный throw не отклонён");
    } catch (AssertionFailedError expected) {}
    assertTrue((BooleanSupplier) () -> { calls.incrementAndGet(); return true; });
    try {
      assertTrue((BooleanSupplier) () -> { calls.incrementAndGet(); return false; });
      throw new AssertionError("False predicate не отклонён");
    } catch (AssertionFailedError expected) {}
    try {
      assertFalse((BooleanSupplier) () -> { calls.incrementAndGet(); throw original; });
      throw new AssertionError("Потерян predicate Throwable");
    } catch (RuntimeException actual) { demand(actual == original); }
    assertEquals(9, calls.get());
    assertEquals(1, messages.get());
    assertEquals(7401, 7401);
  }

  @Test @Timeout(value = 2, threadMode = Timeout.ThreadMode.SAME_THREAD)
  void annotationSame() { assertEquals(7501, 7501); }

  @Test @Timeout(value = 2, threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
  void annotationSeparate() { assertEquals(7601, 7601); }
}
