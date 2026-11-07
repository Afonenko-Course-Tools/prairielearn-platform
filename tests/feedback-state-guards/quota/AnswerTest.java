import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
  private record Value(int id) {}
  @Test void quota() {
    Value value = new Value(29);
    assertEquals(value, value);
  }
}
