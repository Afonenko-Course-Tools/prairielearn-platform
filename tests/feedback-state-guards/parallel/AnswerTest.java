import org.junit.jupiter.api.*;
import org.junit.jupiter.api.parallel.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import java.util.concurrent.*;
import static org.junit.jupiter.api.Assertions.*;

@Execution(ExecutionMode.CONCURRENT)
public class AnswerTest {
  static final CyclicBarrier ordinary = new CyclicBarrier(2), rows = new CyclicBarrier(2),
      dynamic = new CyclicBarrier(2);
  static final Set<Long> ordinaryThreads = ConcurrentHashMap.newKeySet(),
      rowThreads = ConcurrentHashMap.newKeySet(), dynamicThreads = ConcurrentHashMap.newKeySet();
  static void observed(int value, CyclicBarrier barrier, Set<Long> threads) throws Exception {
    threads.add(Thread.currentThread().threadId());
    barrier.await(3, TimeUnit.SECONDS);
    assertEquals(value, value);
    assertTimeoutPreemptively(Duration.ofSeconds(3), () -> {
      assertEquals(value + 1000, value + 1000);
    });
    assertEquals(value + 2000, value + 2000);
  }
  @Test void first() throws Exception { observed(101, ordinary, ordinaryThreads); }
  @Test void second() throws Exception { observed(202, ordinary, ordinaryThreads); }
  @ParameterizedTest(name = "Одинаковое имя") @ValueSource(ints = {301, 302})
  void row(int value) throws Exception { observed(value, rows, rowThreads); }
  @TestFactory List<DynamicTest> generated() {
    return List.of(DynamicTest.dynamicTest("Одинаковое имя", () -> observed(401, dynamic, dynamicThreads)),
                   DynamicTest.dynamicTest("Одинаковое имя", () -> observed(402, dynamic, dynamicThreads)));
  }
  @AfterAll static void distinctWorkers() {
    if (ordinaryThreads.size() != 2 || rowThreads.size() != 2 || dynamicThreads.size() != 2)
      throw new AssertionError("ожидались разные одновременные engine workers для каждой пары");
  }
}
