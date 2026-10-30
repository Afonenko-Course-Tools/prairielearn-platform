import java.util.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import org.prairielearn.feedback.ProjectionAccess;
public class RecordStudent {
  static int reads, fakeReads;
  public static class CustomList extends AbstractList<String> {
    public String get(int index) {
      reads++;
      throw new AssertionError("custom get");
    }
    public int size() {
      reads++;
      throw new AssertionError("custom size");
    }
    public Iterator<String> iterator() {
      reads++;
      throw new AssertionError("custom iterator");
    }
  }
  static record Fake(int id) implements ProjectionAccess {
    public Object $pl$c3$component(int ordinal) {
      fakeReads++;
      return "forged";
    }
  }
  static Object fake() {
    return new Fake(1);
  }
  static Object foreign() throws Exception {
    Class<?> real = Class.forName("ProjectionTwin");
    byte[] bytes = real.getClassLoader().getResourceAsStream("ProjectionTwin.class").readAllBytes();
    class Foreign extends java.security.SecureClassLoader {
      Class<?> create() {
        return defineClass("ProjectionTwin", bytes, 0, bytes.length,
            new java.security.CodeSource(real.getProtectionDomain().getCodeSource().getLocation(),
                (java.security.cert.Certificate[]) null));
      }
    }
    Object object =
        new Foreign().create().getConstructor(int.class, String.class).newInstance(13, "чужой");
    probe(object);
    return object;
  }
  static void denied(Runnable body) {
    try {
      body.run();
      throw new AssertionError("bridge admitted external reader");
    } catch (SecurityException expected) {
    }
  }
  static void probe(Object value) {
    if (value instanceof ProjectionAccess p) {
      denied(() -> p.$pl$c3$component(0));
      denied(() -> ProjectionAccess.require(value));
      try {
        ProjectionAccess.class.getMethod("require", Object.class).invoke(null, value);
        throw new AssertionError("reflection guard admitted");
      } catch (InvocationTargetException e) {
        if (!(e.getCause() instanceof SecurityException))
          throw new AssertionError(e);
      } catch (ReflectiveOperationException e) {
        throw new AssertionError(e);
      }
      try {
        MethodHandles.lookup()
            .findStatic(
                ProjectionAccess.class, "require", MethodType.methodType(void.class, Object.class))
            .invoke(value);
        throw new AssertionError("MH guard admitted");
      } catch (SecurityException expected) {
      } catch (Throwable e) {
        throw new AssertionError(e);
      }
      try {
        ProjectionAccess.class.getMethod("$pl$c3$component", int.class).invoke(value, 0);
        throw new AssertionError("reflection bridge admitted");
      } catch (InvocationTargetException e) {
        if (!(e.getCause() instanceof SecurityException))
          throw new AssertionError(e);
      } catch (ReflectiveOperationException e) {
        throw new AssertionError(e);
      }
      try {
        MethodHandles.lookup()
            .findVirtual(ProjectionAccess.class, "$pl$c3$component",
                MethodType.methodType(Object.class, int.class))
            .invoke(value, 0);
        throw new AssertionError("MH bridge admitted");
      } catch (SecurityException expected) {
      } catch (Throwable e) {
        throw new AssertionError(e);
      }
    }
  }
}
