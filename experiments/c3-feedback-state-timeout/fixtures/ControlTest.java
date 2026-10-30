import org.junit.jupiter.api.*;
public class ControlTest {
  @BeforeAll
  static void outside() throws Throwable {
    Student.controls();
    Student.facade();
    Student.reenter();
  }
  @Test
  @DisplayName("Доверенный helper и запрещённые источники")
  void controls() throws Throwable {
    TrustedHelper.check();
    Student.controls();
    Student.facade();
    Student.reenter();
    Student.foreign();
    org.prairielearn.feedback.Assertions.assertEquals(9, 9);
    Thread child = new Thread(TrustedHelper::check);
    child.start();
    child.join();
    TrustedHelper.check();
  }
  @AfterAll
  static void late() throws Throwable {
    Student.controls();
    Student.facade();
    Student.reenter();
  }
}
