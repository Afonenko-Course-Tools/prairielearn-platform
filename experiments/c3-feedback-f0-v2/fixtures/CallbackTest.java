import org.junit.jupiter.api.*;
import org.junit.jupiter.api.function.*;
import static org.junit.jupiter.api.Assertions.*;
public class CallbackTest {
  @Test
  @DisplayName("Результаты callback без повторного вызова")
  void callbacks() {
    int[] calls = {0}, messages = {0};
    RuntimeException original = new IllegalStateException("Обычная ошибка");
    RuntimeException returned = assertThrows(RuntimeException.class, () -> {
      calls[0]++;
      throw original;
    });
    if (returned != original)
      throw new IllegalStateException("Изменён экземпляр");
    try {
      assertThrows(IllegalArgumentException.class,
          ()
              -> {
            calls[0]++;
            throw original;
          },
          () -> {
            messages[0]++;
            return "Сообщение JUnit";
          });
    } catch (AssertionError expected) {
    }
    try {
      assertThrows(RuntimeException.class, () -> { calls[0]++; });
    } catch (AssertionError expected) {
    }
    String value = assertDoesNotThrow((ThrowingSupplier<String>) () -> {
      calls[0]++;
      return "Возврат";
    });
    if (!value.equals("Возврат"))
      throw new IllegalStateException("Изменён возврат");
    assertDoesNotThrow((Executable) () -> { calls[0]++; });
    try {
      assertDoesNotThrow((Executable) () -> {
        calls[0]++;
        throw original;
      });
    } catch (AssertionError expected) {
    }
    assertTrue((java.util.function.BooleanSupplier) () -> {
      calls[0]++;
      return true;
    });
    try {
      assertTrue((java.util.function.BooleanSupplier) () -> {
        calls[0]++;
        return false;
      });
    } catch (AssertionError expected) {
    }
    try {
      assertFalse((java.util.function.BooleanSupplier) () -> {
        calls[0]++;
        throw original;
      });
    } catch (RuntimeException failure) {
      if (failure != original)
        throw new IllegalStateException("Изменён Throwable");
    }
    if (calls[0] != 9 || messages[0] != 1)
      throw new IllegalStateException("Повторное вычисление callback/message");
  }
  @Test
  @DisplayName("Студент бросил до assertion")
  void before() {
    assertEquals(1, Student.thrownBefore());
  }
  @Test
  @DisplayName("Ранний throw после пройденного assertion")
  void after() {
    assertEquals(1, 1);
    assertEquals(2, Student.thrownBefore());
  }
}
