import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

public class AnswerTest {
  static int accessors, strings, bridgeCalls;
  private record Value(int id, Object data) {
    public int id() { accessors++; throw new AssertionError("accessor"); }
    public Object data() { accessors++; throw new AssertionError("accessor"); }
    public String toString() { strings++; throw new AssertionError("toString"); }
  }
  private record Collision(int id) {
    public Object $pl$c3$component(int ordinal) {
      bridgeCalls++;
      throw new AssertionError("reserved bridge invoked");
    }
  }
  static void demand(boolean ok) { if (!ok) throw new AssertionError("контроль"); }
  @Test void fields() throws Exception {
    Value value = new Value(17, List.of("поле"));
    assertEquals(value, value);
    var bridge = value.getClass().getMethod("$pl$c3$component", int.class);
    bridge.setAccessible(true);
    try {
      bridge.invoke(value, 0);
      throw new AssertionError("direct bridge admitted");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      demand(expected.getCause() instanceof SecurityException);
    }
    demand(accessors == 0 && strings == 0);
  }
  @Test void customList() {
    Value value = new Value(18, new Student.HostileList());
    assertEquals(value, value);
    demand(Student.reads == 0 && accessors == 0 && strings == 0);
  }
  @Test void cycle() {
    Object[] refs = new Object[1];
    Value value = new Value(19, refs);
    refs[0] = value;
    assertEquals(value, value);
    demand(accessors == 0 && strings == 0);
  }
  @Test void foreign() throws Exception {
    Object value = Student.foreign();
    assertEquals(value, value);
    demand(GuardTwin.accessors == 0 && GuardTwin.strings == 0);
  }
  @Test void collision() {
    Collision value = new Collision(20);
    assertEquals(value, value);
    demand(bridgeCalls == 0);
  }
}
