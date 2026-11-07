import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import org.opentest4j.AssertionFailedError;

public class AnswerTest {
  @Test void quota() {
    byte[] expected = new byte[1024], actual = new byte[1024];
    actual[1000] = 1;
    int[] messages = {0};
    boolean caught = false;
    try {
      assertArrayEquals(expected, actual, () -> {
        messages[0]++;
        return "Сообщение JUnit";
      });
    } catch (AssertionFailedError expectedFailure) {
      caught = true;
    }
    if (!caught || messages[0] != 1)
      throw new IllegalStateException("Delegate/message должен исполниться ровно один раз");
  }
}
