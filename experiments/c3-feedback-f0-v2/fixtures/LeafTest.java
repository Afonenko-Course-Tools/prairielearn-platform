import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.api.parallel.*;
import java.util.concurrent.*;
import java.util.stream.*;
import static org.junit.jupiter.api.Assertions.*;
@Execution(ExecutionMode.CONCURRENT)
public class LeafTest {
  static final CountDownLatch barrier = new CountDownLatch(2);
  @ParameterizedTest(name = "Повторяющееся имя")
  @ValueSource(ints = {11, 22})
  void row(int n) {
    assertEquals(n, n);
  }
  @TestFactory
  Stream<DynamicTest> factory() {
    return Stream.of(DynamicTest.dynamicTest("Динамический случай", () -> assertEquals(31, 31)),
        DynamicTest.dynamicTest("Динамический случай", () -> assertEquals(32, 32)));
  }
  @Test
  @DisplayName("Параллельный A")
  void first() throws Exception {
    barrier.countDown();
    if (!barrier.await(3, TimeUnit.SECONDS))
      throw new IllegalStateException("Листья не параллельны");
    assertEquals(101, 101);
  }
  @Test
  @DisplayName("Параллельный B")
  void second() throws Exception {
    barrier.countDown();
    if (!barrier.await(3, TimeUnit.SECONDS))
      throw new IllegalStateException("Листья не параллельны");
    assertEquals(202, 202);
  }
}
