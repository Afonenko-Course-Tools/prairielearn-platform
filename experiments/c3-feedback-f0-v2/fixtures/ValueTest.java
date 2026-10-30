import org.junit.jupiter.api.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
public class ValueTest {
  static int callbacks;
  static class Custom extends AbstractList<String> {
    public String get(int i) {
      callbacks++;
      return "x";
    }
    public int size() {
      callbacks++;
      return 1;
    }
    public Iterator<String> iterator() {
      callbacks++;
      return super.iterator();
    }
    public String toString() {
      callbacks++;
      return "x";
    }
  }
  @Test
  @DisplayName("Байты за коротким окном")
  void bytes() {
    byte[] a = new byte[12000], b = new byte[12000];
    a[11017] = 1;
    b[11017] = 2;
    try {
      assertArrayEquals(a, b);
    } catch (AssertionError expected) {
    }
  }
  @Test
  @DisplayName("Реальная длина byte fixture")
  void actualFixture() {
    byte[] a = ("x ".repeat(5000) + "end").getBytes(java.nio.charset.StandardCharsets.UTF_8);
    assertEquals(10003, a.length);
    assertArrayEquals(a, a);
  }
  @Test
  @DisplayName("Immutable последовательности и identity")
  void sequences() {
    List<?> a =
        List.of(17, "Книга", List.of("Анна", "Борис"), "Печать", 2024, 100, 10.0, "Твёрдый");
    assertEquals(List.of(a), java.util.stream.Stream.of(a).toList());
    Custom custom = new Custom();
    assertNotSame(new Object(), new Object());
    assertNull(null);
    assertNotNull(custom);
    assertSame(custom, custom);
    assertEquals(custom, custom);
    if (callbacks != 0)
      throw new IllegalStateException("Observer вызвал пользовательский код");
    assertArrayEquals(new double[] {1, Double.NaN}, new double[] {1.01, Double.NaN}, .1);
  }
  @Test
  @DisplayName("Квота до копирования массива")
  void quota() {
    byte[] a = new byte[40000];
    assertArrayEquals(a, a);
  }
}
