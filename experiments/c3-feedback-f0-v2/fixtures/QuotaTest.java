import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
public class QuotaTest {
  @Test
  @DisplayName("Snapshot quota до allocation, delegate один раз")
  void quota() {
    byte[] a = new byte[1024], b = new byte[1024];
    b[1000] = 1;
    int[] messages = {0};
    try {
      assertArrayEquals(a, b, () -> {
        messages[0]++;
        return "Сообщение JUnit";
      });
    } catch (AssertionError expected) {
    }
    if (messages[0] != 1)
      throw new IllegalStateException("Delegate/message вычислен повторно");
  }
}
