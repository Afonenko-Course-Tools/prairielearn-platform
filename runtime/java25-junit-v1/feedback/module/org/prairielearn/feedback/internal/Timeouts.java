package org.prairielearn.feedback.internal;
import org.junit.jupiter.api.function.*;
/** Только callback штатного pinned JUnit, без executor/таймера/переноса в student context. */
public final class Timeouts {
  public static Executable executable(State.Grant grant, Executable callback) {
    return callback == null || grant == null ? callback : new ExecutableWrapper(grant, callback);
  }
  public static <T> ThrowingSupplier<T> supplier(State.Grant grant, ThrowingSupplier<T> callback) {
    return callback == null || grant == null ? callback : new SupplierWrapper<>(grant, callback);
  }
  static final class ExecutableWrapper implements Executable {
    private final State.Grant grant;
    private final Executable callback;
    ExecutableWrapper(State.Grant grant, Executable callback) {
      this.grant = grant;
      this.callback = callback;
    }
    public void execute() throws Throwable {
      State.Activation activation = State.activate(grant, true);
      try {
        callback.execute();
      } finally {
        State.deactivate(grant, activation, true);
      }
    }
  }
  static final class SupplierWrapper<T> implements ThrowingSupplier<T> {
    private final State.Grant grant;
    private final ThrowingSupplier<T> callback;
    SupplierWrapper(State.Grant grant, ThrowingSupplier<T> callback) {
      this.grant = grant;
      this.callback = callback;
    }
    public T get() throws Throwable {
      State.Activation activation = State.activate(grant, false);
      try {
        return callback.get();
      } finally {
        State.deactivate(grant, activation, false);
      }
    }
  }
}
