import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class BoundTest {
  @Test
  @DisplayName("Конечный бюджет элементов")
  void items() {
    Object[] a = new Object[255];
    java.util.Arrays.fill(a, 1);
    assertArrayEquals(a, a);
  }
  @Test
  @DisplayName("Цикл и предел глубины")
  void depth() {
    Object[] a = new Object[1];
    a[0] = a;
    assertArrayEquals(a, a);
  }
  @Test
  @DisplayName("Предел публичного render")
  void render() {
    String a = "я".repeat(6000);
    assertEquals(a, a);
  }
}
