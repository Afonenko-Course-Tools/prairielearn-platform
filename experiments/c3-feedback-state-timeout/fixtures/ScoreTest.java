import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;
public class ScoreTest {
  @Test
  @DisplayName("Несколько проверок и reporter")
  void ordinary(TestReporter reporter) {
    for (int i = 0; i < 3; i++) assertEquals(i, i);
    try {
      assertEquals(1, 2);
    } catch (AssertionError caught) {
    }
    assertTimeoutPreemptively(java.time.Duration.ofSeconds(2), () -> {
      assertEquals(15, 15);
      assertEquals(16, 16);
    });
    reporter.publishEntry(
        java.util.Map.of("expected", "Предметное ожидание", "actual", "Предметный результат"));
  }
  @Test
  @DisplayName("Второй обычный случай")
  void second() {
    assertTrue(true);
  }
  @ParameterizedTest(name = "Строка {0}")
  @ValueSource(ints = {0, 1, 2, 3, 4, 5, 6, 7})
  void row(int n) {
    assertEquals(n, n == 7 ? 8 : n);
  }
}
