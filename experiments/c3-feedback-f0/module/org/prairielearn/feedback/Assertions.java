package org.prairielearn.feedback;
/** Только typed pass-through для verifier; capture до устранения boot blocker не реализован. */
public final class Assertions {
  private Assertions() {}
  public static void assertEquals(int a, int b) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b);
  }
  public static void assertEquals(long a, long b) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b);
  }
  public static void assertEquals(double a, double b) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b);
  }
  public static void assertEquals(double a, double b, double d) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b, d);
  }
  public static void assertEquals(Integer a, Integer b) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b);
  }
  public static void assertEquals(int a, int b, java.util.function.Supplier<String> m) {
    org.junit.jupiter.api.Assertions.assertEquals(a, b, m);
  }
}
