import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class TypedTest {
  static int calls, messages;
  @BeforeEach
  void reset() {
    calls = 0;
    messages = 0;
  }
  static int answer() {
    calls++;
    return 42;
  }
  @Test
  @DisplayName("Типизированные проверки")
  void typed() {
    assertEquals(42, answer());
    assertEquals(9000000000L, 9000000000L);
    assertEquals(1.0d, 1.01d, .1d);
    assertEquals(Double.NaN, Double.NaN);
    assertEquals(-0.0d, +0.0d, 0.0d);
    assertEquals((Integer) null, (Integer) null);
    assertEquals(1, 1, () -> {
      messages++;
      return "служебное сообщение";
    });
    try {
      assertEquals(41, 42, () -> {
        messages++;
        return "служебное сообщение";
      });
    } catch (AssertionError expected) {
    }
    for (int i = 0; i < 6000; i++) assertEquals(1, 1);
    if (calls != 1 || messages != 1)
      throw new IllegalStateException("Повторное вычисление");
  }
  @Test
  @DisplayName("Исходный отказ")
  void failed() {
    assertEquals(41, answer());
  }
}
