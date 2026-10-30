package org.prairielearn.feedback;
/** Тестовый utility отдельного diagnostic mode, не API candidate observer. */
public final class PublicationControl {
  public static void repeated(org.junit.jupiter.api.function.Executable callback) throws Exception {
    org.prairielearn.feedback.internal.GrantProbe.repeated(callback);
  }
  public static void direct(org.junit.jupiter.api.function.Executable callback) throws Throwable {
    org.prairielearn.feedback.internal.GrantProbe.direct(callback);
  }
  public static void stale(org.junit.jupiter.api.function.Executable callback) {
    org.prairielearn.feedback.internal.GrantProbe.stale(callback);
  }
  public static boolean entered() {
    return org.prairielearn.feedback.internal.PublicationProbe.entered();
  }
  public static boolean stable() throws Exception {
    return org.prairielearn.feedback.internal.PublicationProbe.stable();
  }
  public static void release() {
    org.prairielearn.feedback.internal.PublicationProbe.release();
  }
}
