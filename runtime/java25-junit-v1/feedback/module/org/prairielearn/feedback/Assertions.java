package org.prairielearn.feedback;
import org.prairielearn.feedback.internal.State;
public final class Assertions {
  private Assertions() {}
  public static void assertEquals(int a, int b) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(long a, long b) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(double a, double b) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(Integer a, Integer b) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(Object a, Object b) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(double a, double b, double d) {
    var t = State.begin("равенство с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, d);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(int a, int b, String m) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(Object a, Object b, String m) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(int a, int b, java.util.function.Supplier<String> m) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(Object a, Object b, java.util.function.Supplier<String> m) {
    var t = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(byte[] a, byte[] b) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(int[] a, int[] b) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(Object[] a, Object[] b) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(double[] a, double[] b, double d) {
    var t = State.begin("равенство массивов с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, d);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertTrue(boolean b) {
    var t = State.begin("значение предиката", true, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertTrue(b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertFalse(boolean b) {
    var t = State.begin("значение предиката", false, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertFalse(b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertSame(Object a, Object b) {
    var t = State.begin("совпадение ссылок", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertSame(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertSame(Object a, Object b, String m) {
    var t = State.begin("совпадение ссылок", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertSame(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNotSame(Object a, Object b) {
    var t = State.begin("различие ссылок", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotSame(a, b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNotSame(Object a, Object b, String m) {
    var t = State.begin("различие ссылок", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotSame(a, b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNull(Object b) {
    var t = State.begin("null", null, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNull(b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNull(Object b, String m) {
    var t = State.begin("null", null, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNull(b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNotNull(Object b) {
    var t = State.begin("не null", null, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotNull(b);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertNotNull(Object b, String m) {
    var t = State.begin("не null", null, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotNull(b, m);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertTrue(java.util.function.BooleanSupplier callback) {
    var t = State.begin("значение предиката", true, "не вычислено", null);
    try {
      org.junit.jupiter.api.Assertions.assertTrue((java.util.function.BooleanSupplier) () -> {
        try {
          boolean actual = callback.getAsBoolean();
          State.callback(t, actual);
          return actual;
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      });
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertFalse(java.util.function.BooleanSupplier callback) {
    var t = State.begin("значение предиката", false, "не вычислено", null);
    try {
      org.junit.jupiter.api.Assertions.assertFalse((java.util.function.BooleanSupplier) () -> {
        try {
          boolean actual = callback.getAsBoolean();
          State.callback(t, actual);
          return actual;
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      });
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T extends Throwable> T assertThrows(
      Class<T> type, org.junit.jupiter.api.function.Executable callback) {
    var t = State.begin("тип исключения", type, "не бросил", null);
    try {
      T result = org.junit.jupiter.api.Assertions.assertThrows(type, () -> {
        try {
          callback.execute();
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      });
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T extends Throwable> T assertThrows(
      Class<T> type, org.junit.jupiter.api.function.Executable callback, String m) {
    var t = State.begin("тип исключения", type, "не бросил", null);
    try {
      T result = org.junit.jupiter.api.Assertions.assertThrows(type, () -> {
        try {
          callback.execute();
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      }, m);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T extends Throwable> T assertThrows(Class<T> type,
      org.junit.jupiter.api.function.Executable callback, java.util.function.Supplier<String> m) {
    var t = State.begin("тип исключения", type, "не бросил", null);
    try {
      T result = org.junit.jupiter.api.Assertions.assertThrows(type, () -> {
        try {
          callback.execute();
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      }, m);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertDoesNotThrow(org.junit.jupiter.api.function.Executable callback) {
    var t = State.begin("нормальное завершение", "не бросил", "не выполнено", null);
    try {
      org.junit.jupiter.api.Assertions.assertDoesNotThrow(() -> {
        try {
          callback.execute();
          State.callback(t, "не бросил");
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      });
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T> T assertDoesNotThrow(
      org.junit.jupiter.api.function.ThrowingSupplier<T> callback) {
    var t = State.begin("нормальный возврат", "не бросил", "не выполнено", null);
    try {
      T result = org.junit.jupiter.api.Assertions.assertDoesNotThrow(() -> {
        try {
          T actual = callback.get();
          State.callback(t, actual);
          return actual;
        } catch (Throwable actual) {
          State.callback(t, actual.getClass());
          throw actual;
        }
      });
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertTimeoutPreemptively(
      java.time.Duration duration, org.junit.jupiter.api.function.Executable callback) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(
          duration, org.prairielearn.feedback.internal.Timeouts.executable(grant, callback));
      State.callback(t, "не бросил");
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static void assertTimeoutPreemptively(java.time.Duration duration,
      org.junit.jupiter.api.function.Executable callback, String message) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(duration,
          org.prairielearn.feedback.internal.Timeouts.executable(grant, callback), message);
      State.callback(t, "не бросил");
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static void assertTimeoutPreemptively(java.time.Duration duration,
      org.junit.jupiter.api.function.Executable callback,
      java.util.function.Supplier<String> message) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(duration,
          org.prairielearn.feedback.internal.Timeouts.executable(grant, callback), message);
      State.callback(t, "не бросил");
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static <T> T assertTimeoutPreemptively(
      java.time.Duration duration, org.junit.jupiter.api.function.ThrowingSupplier<T> callback) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      T result = org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(
          duration, org.prairielearn.feedback.internal.Timeouts.supplier(grant, callback));
      State.callback(t, result);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static <T> T assertTimeoutPreemptively(java.time.Duration duration,
      org.junit.jupiter.api.function.ThrowingSupplier<T> callback, String message) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      T result = org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(
          duration, org.prairielearn.feedback.internal.Timeouts.supplier(grant, callback), message);
      State.callback(t, result);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static <T> T assertTimeoutPreemptively(java.time.Duration duration,
      org.junit.jupiter.api.function.ThrowingSupplier<T> callback,
      java.util.function.Supplier<String> message) {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      T result = org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(
          duration, org.prairielearn.feedback.internal.Timeouts.supplier(grant, callback), message);
      State.callback(t, result);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static <T, E extends Throwable> T assertTimeoutPreemptively(java.time.Duration duration,
      org.junit.jupiter.api.function.ThrowingSupplier<T> callback,
      java.util.function.Supplier<String> message,
      org.junit.jupiter.api.Assertions.TimeoutFailureFactory<E> factory) throws E {
    var t = State.begin("preemptive timeout",
        duration == null ? "null" : duration.getSeconds() + "s/" + duration.getNano() + "ns",
        "<unavailable>", null);
    var grant = State.grant(t);
    try {
      T result = org.junit.jupiter.api.Assertions.assertTimeoutPreemptively(duration,
          org.prairielearn.feedback.internal.Timeouts.supplier(grant, callback), message, factory);
      State.callback(t, result);
      State.end(t, "returned");
      return result;
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    } finally {
      State.revoke(grant);
    }
  }
  public static void assertArrayEquals(int[] a, int[] b, String message) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, message);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(Object[] a, Object[] b, String message) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, message);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertTrue(boolean actual, String message) {
    var t = State.begin("значение предиката", true, actual, null);
    try {
      org.junit.jupiter.api.Assertions.assertTrue(actual, message);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T> T fail() {
    var t = State.begin("запрещённая ветвь", "нормальное завершение", "ветвь достигнута", null);
    try {
      return org.junit.jupiter.api.Assertions.fail();
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static <T> T fail(String message) {
    var t = State.begin("запрещённая ветвь", "нормальное завершение", "ветвь достигнута", null);
    try {
      return org.junit.jupiter.api.Assertions.fail(message);
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(
      byte[] a, byte[] b, java.util.function.Supplier<String> message) {
    var t = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, message);
      State.end(t, "returned");
    } catch (Throwable error) {
      State.end(t, "threw");
      throw error;
    }
  }
  public static void assertEquals(double a, double b, double d, String message) {
    var token = State.begin("равенство с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertEquals(double a, double b, double d, java.util.function.Supplier<String> message) {
    var token = State.begin("равенство с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(double[] a, double[] b, double d, String message) {
    var token = State.begin("равенство массивов с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(double[] a, double[] b, double d, java.util.function.Supplier<String> message) {
    var token = State.begin("равенство массивов с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertEquals(float a, float b, float d, String message) {
    var token = State.begin("равенство с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertEquals(float a, float b, float d, java.util.function.Supplier<String> message) {
    var token = State.begin("равенство с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(float[] a, float[] b, float d, String message) {
    var token = State.begin("равенство массивов с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(float[] a, float[] b, float d, java.util.function.Supplier<String> message) {
    var token = State.begin("равенство массивов с допуском", a, b, d);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b, d, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertEquals(long a, long b, String message) {
    var token = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertTrue(boolean actual, java.util.function.Supplier<String> message) {
    var token = State.begin("значение предиката", true, actual, null);
    try {
      org.junit.jupiter.api.Assertions.assertTrue(actual, message);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertEquals(char a, char b) {
    var token = State.begin("равенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertEquals(a, b);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertNotEquals(long a, long b) {
    var token = State.begin("неравенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotEquals(a, b);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertNotEquals(int a, int b) {
    var token = State.begin("неравенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotEquals(a, b);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertNotEquals(Object a, Object b) {
    var token = State.begin("неравенство", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertNotEquals(a, b);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static void assertArrayEquals(long[] a, long[] b) {
    var token = State.begin("равенство массивов", a, b, null);
    try {
      org.junit.jupiter.api.Assertions.assertArrayEquals(a, b);
      State.end(token, "returned");
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
  public static <T> T assertInstanceOf(Class<T> expectedType, Object actual) {
    var token = State.begin("тип значения", expectedType, actual, null);
    try {
      T result = org.junit.jupiter.api.Assertions.assertInstanceOf(expectedType, actual);
      State.end(token, "returned");
      return result;
    } catch (Throwable error) {
      State.end(token, "threw");
      throw error;
    }
  }
}
