package org.prairielearn.feedback;
import java.util.*;
import org.prairielearn.feedback.internal.State;
/** Только lifecycle адаптера; все четыре mutating entry points проверяются внутри module. */
public final class Gate {
  private Gate() {}
  public static void bind() {
    State.bind();
  }
  public static void register(String id) {
    State.register(id);
  }
  public static void start(String id) {
    State.start(id);
  }
  public static List<Map<String, String>> finish(String id) {
    return State.finish(id);
  }
}
