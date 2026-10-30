import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
public class RecordTest {
  static int constructors, getters, factories, equals, accessors, strings, messages;
  private record Value(int id, String title, List<String> authors, double price) {
    Value {
      constructors++;
    }
    public int id() {
      accessors++;
      return id;
    }
    public String toString() {
      strings++;
      return "BASELINE_RENDER";
    }
    public boolean equals(Object other) {
      equals++;
      return other instanceof Value v && id == v.id && Objects.equals(title, v.title)
          && authors.equals(v.authors) && price == v.price;
    }
  }
  private record Envelope(Value value, Object[] others) {}
  private record Unsupported(Object value) {}
  private static final class Source {
    int id() {
      getters++;
      return 7;
    }
    String title() {
      getters++;
      return "null\n\"заголовок";
    }
    List<String> authors() {
      getters++;
      return List.of("А", "Б");
    }
    double price() {
      getters++;
      return 1.25;
    }
  }
  static Value make() {
    factories++;
    Source source = new Source();
    return new Value(source.id(), source.title(), source.authors(), source.price());
  }
  @Test
  void singleEvaluation() {
    constructors = getters = factories = equals = accessors = strings = messages = 0;
    Value a = make(), b = make();
    assertEquals(a, b, () -> {
      messages++;
      return "unused";
    });
    assertArrayEquals(new Value[] {a}, new Value[] {b});
    assertEquals(2, constructors);
    assertEquals(8, getters);
    assertEquals(2, factories);
    assertEquals(2, equals);
    assertEquals(0, accessors);
    assertEquals(0, strings);
    assertEquals(0, messages);
    try {
      assertEquals(1, 2, () -> {
        messages++;
        return "различие";
      });
    } catch (AssertionError expected) {
    }
    assertEquals(1, messages);
  }
  @Test
  void earlyThrow() {
    try {
      failBefore();
    } catch (IllegalStateException expected) {
    }
  }
  static Value failBefore() {
    throw new IllegalStateException("до assertion");
  }
  @Test
  void nestedSafe() {
    Value value = new Value(9, "Книга", List.of("Автор"), 2.5);
    Envelope a = new Envelope(value, new Object[] {List.of("один", "два"), new int[] {3, 4}});
    assertEquals(a, a);
    byte[] expected = new byte[12000], actual = new byte[12000];
    expected[11017] = 1;
    actual[11017] = 2;
    try {
      assertArrayEquals(expected, actual);
      throw new AssertionError("difference lost");
    } catch (org.opentest4j.AssertionFailedError caught) {
    }
  }
  @Test
  void customListNeverRead() {
    RecordStudent.CustomList list = new RecordStudent.CustomList();
    Value a = new Value(1, "Книга", list, 0);
    assertSame(a, a); // исходный JUnit не обязан обходить record
    assertEquals(a, a);
    assertEquals(0, RecordStudent.reads);
  }
  @Test
  void cycle() {
    Object[] a = new Object[1];
    Envelope value = new Envelope(null, a);
    a[0] = value;
    assertEquals(value, value);
    Object[] pure = new Object[1];
    pure[0] = pure;
    assertArrayEquals(pure, pure);
  }
  @Test
  void unsupported() {
    Unsupported a = new Unsupported(new Object());
    assertEquals(a, a);
    Value value = new Value(1, null, List.of("null"), 0);
    assertEquals(value, value);
  }
  @BeforeAll
  @AfterAll
  static void outside() {
    RecordStudent.probe(new Value(1, "вне leaf", List.of("автор"), 0));
  }
  @Test
  void authority() throws Exception {
    Value a = new Value(1, "книга", List.of("автор"), 0);
    RecordStudent.probe(a);
    Object fake = RecordStudent.fake();
    assertEquals(fake, fake);
    Object foreign = RecordStudent.foreign();
    assertEquals(foreign, foreign);
    assertEquals(new ProjectionTwin(13, "подлинный"), new ProjectionTwin(13, "подлинный"));
    assertEquals(0, RecordStudent.fakeReads);
    assertEquals(1, 1);
  }
}
