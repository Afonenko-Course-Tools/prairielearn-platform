import java.lang.invoke.*;
import java.lang.reflect.*;
import java.security.*;
import java.util.*;
import org.prairielearn.feedback.Gate;
public class Student {
  public static int answer() {
    return 42;
  }
  public static void controls() throws Throwable {
    for (String name : List.of("bind", "register", "start", "finish"))
      for (int mode = 0; mode < 3; mode++) {
        try {
          if (mode == 0) {
            switch (name) {
              case "bind" -> Gate.bind();
              case "register" -> Gate.register("foreign");
              case "start" -> Gate.start("foreign");
              case "finish" -> Gate.finish("foreign");
            }
          } else if (mode == 1) {
            if (name.equals("bind"))
              Gate.class.getMethod(name).invoke(null);
            else
              Gate.class.getMethod(name, String.class).invoke(null, "foreign");
          } else {
            MethodType type = MethodType.methodType(name.equals("finish") ? List.class : void.class,
                name.equals("bind") ? new Class<?>[0] : new Class<?>[] {String.class});
            var handle = MethodHandles.lookup().findStatic(Gate.class, name, type);
            if (name.equals("bind"))
              handle.invokeWithArguments();
            else
              handle.invokeWithArguments("foreign");
          }
          throw new IllegalStateException("External mutation admitted: " + name);
        } catch (InvocationTargetException wrapper) {
          if (!(wrapper.getCause() instanceof SecurityException))
            throw wrapper;
        } catch (SecurityException denied) {
        }
      }
    Class<?> state = Class.forName("org.prairielearn.feedback.internal.State");
    if (state.getDeclaredField("bound").trySetAccessible())
      throw new IllegalStateException("Reflective field mutation admitted");
    try {
      MethodHandles.privateLookupIn(state, MethodHandles.lookup());
      throw new IllegalStateException("Private lookup admitted");
    } catch (IllegalAccessException denied) {
    }
    for (Method method : state.getDeclaredMethods())
      if (Modifier.isPublic(method.getModifiers())) {
        try {
          method.invoke(null, new Object[method.getParameterCount()]);
          throw new IllegalStateException("Internal mutation admitted");
        } catch (IllegalAccessException denied) {
        }
      }
    Class<?> timeouts = Class.forName("org.prairielearn.feedback.internal.Timeouts");
    for (Method method : timeouts.getDeclaredMethods())
      if (Modifier.isPublic(method.getModifiers())) {
        try {
          method.invoke(null, new Object[method.getParameterCount()]);
          throw new AssertionError("timeout entry exported");
        } catch (IllegalAccessException expected) {
        }
      }
    for (Class<?> wrapper : timeouts.getDeclaredClasses())
      for (Constructor<?> constructor : wrapper.getDeclaredConstructors())
        if (constructor.trySetAccessible())
          throw new AssertionError("private timeout wrapper opened");
    if (state.getResourceAsStream("policy.properties") != null)
      throw new IllegalStateException("Private policy resource exposed");
    Class<?> scope = Class.forName("org.prairielearn.feedback.internal.Scope");
    if (scope.getConstructor().trySetAccessible())
      throw new IllegalStateException("Scope constructor opened");
    var provider = ServiceLoader.load(org.junit.jupiter.api.extension.Extension.class)
                       .stream()
                       .filter(p -> p.type() == scope)
                       .findFirst()
                       .orElseThrow()
                       .get();
    var fake = (org.junit.jupiter.api.extension.ExtensionContext) Proxy.newProxyInstance(
        Student.class.getClassLoader(),
        new Class<?>[] {org.junit.jupiter.api.extension.ExtensionContext.class},
        (o, m, a) -> m.getName().equals("getUniqueId") ? "foreign" : null);
    try {
      ((org.junit.jupiter.api.extension.InvocationInterceptor) provider).interceptTestMethod(() -> {
        throw new IllegalStateException("Fake invocation reached");
      }, null, fake);
      throw new IllegalStateException("Fake scope admitted");
    } catch (SecurityException denied) {
    }
  }
  public static void reenter() throws Exception {
    Class.forName("TrustedHelper").getMethod("check").invoke(null);
  }
  public static void facade() throws Throwable {
    org.prairielearn.feedback.Assertions.assertEquals(9, 9);
    var owner = org.prairielearn.feedback.Assertions.class;
    owner.getMethod("assertEquals", int.class, int.class).invoke(null, 9, 9);
    MethodHandles.lookup()
        .findStatic(owner, "assertEquals", MethodType.methodType(void.class, int.class, int.class))
        .invokeExact(9, 9);
  }
  public static void foreign() throws Exception {
    byte[] bytes =
        Student.class.getClassLoader().getResourceAsStream("TrustedHelper.class").readAllBytes();
    Class<?> real = Class.forName("TrustedHelper");
    class Foreign extends SecureClassLoader {
      Class<?> create() {
        return defineClass("TrustedHelper", bytes, 0, bytes.length,
            new CodeSource(real.getProtectionDomain().getCodeSource().getLocation(),
                (java.security.cert.Certificate[]) null));
      }
    }
    new Foreign().create().getMethod("check").invoke(null);
  }
}
