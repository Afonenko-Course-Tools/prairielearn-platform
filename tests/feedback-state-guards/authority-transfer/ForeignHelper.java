import static org.junit.jupiter.api.Assertions.assertEquals;

/** Байты этого настоящего transformed helper загружаются повторно с другой Class identity. */
public class ForeignHelper {
  public static void check() {
    Student.foreignReached();
    assertEquals(999004, 999004);
  }
}
