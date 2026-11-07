import java.util.AbstractList;
import java.util.Iterator;
public class Student {
  public static int reads;
  public static final class HostileList extends AbstractList<Object> {
    public Object get(int index) { reads++; throw new AssertionError("get"); }
    public int size() { reads++; throw new AssertionError("size"); }
    public Iterator<Object> iterator() { reads++; throw new AssertionError("iterator"); }
    public String toString() { reads++; throw new AssertionError("toString"); }
  }
  public static Object foreign() throws Exception {
    Class<?> original = Class.forName("GuardTwin");
    byte[] bytes;
    try (var in = original.getResourceAsStream("/GuardTwin.class")) {
      if (in == null) throw new AssertionError("class bytes");
      bytes = in.readAllBytes();
    }
    class Foreign extends java.security.SecureClassLoader {
      Class<?> create() {
        return defineClass("GuardTwin", bytes, 0, bytes.length,
            new java.security.CodeSource(original.getProtectionDomain().getCodeSource().getLocation(),
                (java.security.cert.Certificate[]) null));
      }
    }
    Class<?> foreign = new Foreign().create();
    if (foreign == original || !foreign.getProtectionDomain().getCodeSource().getLocation()
        .equals(original.getProtectionDomain().getCodeSource().getLocation()))
      throw new AssertionError("foreign identity");
    return foreign.getConstructor(int.class).newInstance(21);
  }
}
