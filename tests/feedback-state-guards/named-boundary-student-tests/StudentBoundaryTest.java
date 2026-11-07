import org.junit.jupiter.api.*;
import org.junit.jupiter.api.extension.*;
import org.junit.jupiter.api.parallel.*;
import static org.junit.jupiter.api.Assertions.*;
@ExtendWith(StudentBoundaryTest.StudentExtension.class)
public class StudentBoundaryTest {
  public static final class StudentExtension implements BeforeEachCallback {
    public void beforeEach(ExtensionContext context) throws Exception { boundary(); }
  }
  @FunctionalInterface interface Refused { void run() throws Exception; }
  static void denied(Refused action) throws Exception {
    try { action.run(); } catch (SecurityException expected) { return; }
    throw new AssertionError("Неуполномоченный lifecycle принят");
  }
  static void boundary() throws Exception {
    Module observer = Class.forName("org.prairielearn.feedback.PlatformJUnitAdapter").getModule();
    Module caller = StudentBoundaryTest.class.getModule();
    String[][] targets = {
      {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor"},
      {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution"},
      {"org.junit.platform.launcher", "org.junit.platform.launcher.core"},
      {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical"}
    };
    for (String[] target : targets) {
      Module module = ModuleLayer.boot().findModule(target[0]).orElseThrow();
      assertTrue(module.isNamed());
      assertFalse(module.getDescriptor().isAutomatic());
      assertFalse(module.getDescriptor().isOpen());
      assertFalse(module.isOpen(target[1], caller));
      assertFalse(module.isOpen(target[1], observer));
      if (target[0].equals("org.junit.jupiter.engine")) {
        assertFalse(module.isExported(target[1], caller));
        assertFalse(module.isExported(target[1], observer));
      }
    }
    assertFalse(observer.isOpen("org.prairielearn.feedback.internal", caller));
    Class<?> adapter = Class.forName("org.prairielearn.feedback.PlatformJUnitAdapter");
    org.junit.platform.launcher.TestExecutionListener fresh =
        (org.junit.platform.launcher.TestExecutionListener) adapter.getConstructor().newInstance();
    denied(() -> fresh.testPlanExecutionStarted(null));
    denied(() -> fresh.dynamicTestRegistered(null));
    denied(() -> fresh.executionStarted(null));
    denied(() -> fresh.executionSkipped(null, null));
    denied(() -> fresh.executionFinished(null, null));
    denied(() -> fresh.reportingEntryPublished(null, null));
    denied(() -> fresh.testPlanExecutionFinished(null));
    java.nio.file.Path marker = java.nio.file.Files.createTempFile("named-main-", ".json");
    try {
      java.nio.file.Files.writeString(marker, "не параметры запуска");
      for (String[] args : new String[][] {null, new String[0], {marker.toString()}}) {
        try { adapter.getMethod("main", String[].class).invoke(null, (Object) args); }
        catch (java.lang.reflect.InvocationTargetException expected) {
          if (!(expected.getCause() instanceof SecurityException)) throw expected;
          continue;
        }
        throw new AssertionError("Повторный main принят");
      }
      assertEquals("не параметры запуска", java.nio.file.Files.readString(marker));
    } finally { java.nio.file.Files.deleteIfExists(marker); }
  }
  @Test void boundaryWithoutPolicy(TestReporter reporter) throws Exception {
    boundary();
    assertEquals(42, Candidate.answer());
    reporter.publishEntry(java.util.Map.of("expected", "не публиковать", "actual", "не публиковать"));
  }
}
