package org.prairielearn.feedback.internal;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
/** Только диагностический класс: в обычный candidate module не компилируется. */
public final class PublicationProbe {
  private static final CountDownLatch entered = new CountDownLatch(1),
                                      release = new CountDownLatch(1), done = new CountDownLatch(1);
  private static final AtomicBoolean claimed = new AtomicBoolean();
  private static volatile List<Map<String, String>> frozen;
  private static volatile String bytes;
  public static void pause(String stage) {
    if (!stage.equals(System.getProperty("c3.pause")) || !claimed.compareAndSet(false, true))
      return;
    entered.countDown();
    try {
      boolean wait = true;
      while (wait) try {
          wait = !release.await(3, TimeUnit.SECONDS);
          if (wait)
            throw new AssertionError("release не получен");
        } catch (InterruptedException ignored) {
        }
    } finally {
      done.countDown();
    }
  }
  public static void capture(List<Map<String, String>> output) {
    if (frozen == null && entered.getCount() == 0) {
      frozen = output;
      bytes = output.toString();
    }
  }
  public static boolean entered() {
    return entered.getCount() == 0;
  }
  public static void release() {
    release.countDown();
  }
  public static boolean stable() throws Exception {
    release();
    if (!done.await(2, TimeUnit.SECONDS))
      throw new AssertionError("worker не освобождён");
    if (frozen == null || !bytes.equals(frozen.toString()))
      return false;
    try {
      frozen.add(Map.of());
      throw new AssertionError("mutable list");
    } catch (UnsupportedOperationException expected) {
    }
    try {
      frozen.getFirst().put("actual", "changed");
      throw new AssertionError("mutable map");
    } catch (UnsupportedOperationException expected) {
    }
    return bytes.equals(frozen.toString());
  }
}
