import java.time.Duration;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.function.Executable;
import static org.junit.jupiter.api.Assertions.*;

@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class AnswerTest {
  public record Value(int id) {}
  static final String PREFIX = "[engine:junit-jupiter]/[class:AnswerTest]/[method:";
  @BeforeAll static void before() throws Throwable {
    Student.structural();
    Student.audit("before", PREFIX + "worker()]", PREFIX + "worker()]", new Value(4000));
  }
  @Test @Order(1) void authority() throws Throwable {
    Value value = new Value(4100);
    assertEquals(4101, 4101);
    assertEquals(value, value);
    Student.audit("normal", PREFIX + "authority()]", PREFIX + "worker()]", value);
    assertEquals(4102, 4102);
  }
  @Test @Order(2) void worker() {
    assertTimeoutPreemptively(Duration.ofSeconds(3), (Executable) () -> {
      assertEquals(4201, 4201);
      Student.audit("worker", PREFIX + "worker()]", PREFIX + "worker()]", new Value(4200));
      assertEquals(4202, 4202);
    });
  }
  @AfterAll static void after() throws Throwable {
    Student.audit("after", PREFIX + "worker()]", PREFIX + "worker()]", new Value(4300));
    System.out.println(Student.summary());
  }
}
