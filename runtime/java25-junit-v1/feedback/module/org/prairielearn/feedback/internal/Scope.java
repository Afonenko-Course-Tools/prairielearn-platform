package org.prairielearn.feedback.internal;
import java.lang.reflect.Method;
import org.junit.jupiter.api.extension.*;
/** Синхронная область именно текущего Jupiter invocation, без наследования child threads. */
public final class Scope implements InvocationInterceptor {
  private void invoke(Invocation<Void> invocation, ExtensionContext context) throws Throwable {
    State.open(context.getUniqueId());
    try {
      invocation.proceed();
    } finally {
      State.close();
    }
  }
  public void interceptTestMethod(Invocation<Void> i, ReflectiveInvocationContext<Method> m,
      ExtensionContext c) throws Throwable {
    invoke(i, c);
  }
  public void interceptTestTemplateMethod(Invocation<Void> i, ReflectiveInvocationContext<Method> m,
      ExtensionContext c) throws Throwable {
    invoke(i, c);
  }
  public void interceptDynamicTest(
      Invocation<Void> i, DynamicTestInvocationContext m, ExtensionContext c) throws Throwable {
    invoke(i, c);
  }
}
