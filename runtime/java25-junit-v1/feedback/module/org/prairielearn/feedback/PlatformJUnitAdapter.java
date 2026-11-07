package org.prairielearn.feedback;
import java.lang.reflect.*;
import java.lang.classfile.ClassFile;
import java.io.*;
import org.json.simple.parser.JSONParser;
import java.nio.file.*;
import java.util.*;
import org.json.simple.*;
import org.junit.platform.launcher.*;
import org.junit.platform.engine.*;
import org.junit.platform.engine.reporting.ReportEntry;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.engine.support.descriptor.ClassSource;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import org.junit.platform.launcher.core.*;
import org.junit.platform.reporting.legacy.xml.LegacyXmlReportGeneratingListener;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClass;
import org.prairielearn.feedback.internal.RuntimeIdentity;

/** Полезная обратная связь рядом со штатным XML отчётом JUnit. */
public final class PlatformJUnitAdapter implements TestExecutionListener {
  public PlatformJUnitAdapter() {}

  private enum Phase { PREPARED, LAUNCHING, RUNNING, FINISHED, RETIRED }
  private static volatile PlatformJUnitAdapter authorizedListener;
  private Phase phase = Phase.PREPARED;
  private boolean integrityFailure;
  private final Set<Class<?>> reportingCallers = Collections.newSetFromMap(new IdentityHashMap<>());

  private void engineCall(String event) {
    if (this != authorizedListener)
      throw new SecurityException("Unauthorized JUnit listener instance");
    try {
      Phase expected = event.equals("testPlanExecutionStarted") ? Phase.LAUNCHING : Phase.RUNNING;
      if (phase != expected)
        throw new SecurityException("Invalid JUnit listener phase");
      RuntimeIdentity.callback(event, reportingCallers);
    } catch (RuntimeException | Error invalid) {
      integrityFailure = true;
      throw invalid;
    }
  }
  private void bindReportingOrigin(JSONObject params) throws Exception {
    bindReportingClasses(params, "trusted_classes_root", "trusted_classes");
    if (!observeAssertions)
      bindReportingClasses(params, "student_classes_root", "student_classes");
  }
  private void bindReportingClasses(JSONObject params, String rootKey, String classesKey) throws Exception {
    if (!(params.get(rootKey) instanceof String root)
        || !(params.get(classesKey) instanceof JSONArray classes))
      throw new IOException("Missing private trusted reporting binding");
    Path expected = Path.of(root).toRealPath();
    ClassLoader loader = PlatformJUnitAdapter.class.getClassLoader();
    for (Object value : classes) {
      if (!(value instanceof String name))
        throw new IOException("Invalid private trusted class");
      Class<?> type = Class.forName(name, false, loader);
      verifyOrigin(type, loader, expected);
      if (!reportingCallers.add(type))
        throw new IOException("Duplicate private trusted class");
    }
  }
  private final Map<String, String> outcomes = new TreeMap<>();
  private final Set<String> successfulContainers = new LinkedHashSet<>();
  private Set<String> studentClasses = Set.of();
  private String submissionMode;
  private boolean observeAssertions;
  private Path studentRoot;
  private void bindStudentOrigin(JSONObject params) throws Exception {
    Object mode = params.get("submission_mode"), root = params.get("student_classes_root"),
           classes = params.get("student_classes");
    if (!(mode instanceof String value)
        || !Set.of("implementation", "student-tests").contains(value)
        || !(root instanceof String path) || !(classes instanceof JSONArray list))
      throw new IOException("Invalid private submission origin binding");
    submissionMode = value;
    studentRoot = Path.of(path).toRealPath();
    if (!Files.isDirectory(studentRoot))
      throw new IOException("Private student output directory missing");
    Set<String> names = new HashSet<>();
    for (Object name : list)
      if (!(name instanceof String text) || text.isEmpty() || !names.add(text))
        throw new IOException("Invalid compiled student inventory");
    Set<String> actual = new HashSet<>();
    try (var files = Files.walk(studentRoot)) {
      for (Path file : files.filter(entry -> entry.toString().endsWith(".class")).toList()) {
        if (Files.isSymbolicLink(file) || !Files.isRegularFile(file))
          throw new IOException("Unsafe compiled student file");
        actual.add(ClassFile.of().parse(file).thisClass().asInternalName().replace('/', '.'));
      }
    }
    if (!actual.equals(names))
      throw new IOException("Private compiled student inventory differs from output");
    studentClasses = Set.copyOf(names);
  }
  private boolean studentAssertionOrigin(Throwable failure) throws Exception {
    if (!"implementation".equals(submissionMode) || failure.getStackTrace().length == 0)
      return false;
    StackTraceElement frame = failure.getStackTrace()[0];
    String name = frame.getClassName();
    if (!studentClasses.contains(name))
      return false;
    ClassLoader loader = PlatformJUnitAdapter.class.getClassLoader();
    Class<?> origin = Class.forName(name, false, loader);
    verifyOrigin(origin, loader, studentRoot);
    return Objects.equals(frame.getClassLoaderName(), loader.getName())
        && Objects.equals(frame.getModuleName(), origin.getModule().getName());
  }
  private final Map<String, String> failures = new TreeMap<>();
  private final Map<Class<?>, String> consoleFailures = new HashMap<>();
  private void bindConsoleSupport(Object marker) throws Exception {
    if (marker == null)
      return;
    if (!(marker instanceof String root))
      throw new IOException("Invalid trusted console origin marker");
    Path expected = Path.of(root).toRealPath();
    ClassLoader loader = PlatformJUnitAdapter.class.getClassLoader();
    Class<?> owner = Class.forName("coursesupport.JavaProcess", false, loader);
    verifyOrigin(owner, loader, expected);
    String[] names = {"UncaughtStudentException", "StudentTimeout", "StudentOutputLimit"};
    String[] kinds = {"runtime", "timeout", "output-limit"};
    for (int i = 0; i < names.length; i++) {
      Class<?> type = Class.forName("coursesupport.JavaProcess$" + names[i], false, loader);
      verifyOrigin(type, loader, expected);
      int modifiers = type.getModifiers();
      if (type.getDeclaringClass() != owner
          || type.getSuperclass() != AssertionError.class || !Modifier.isPublic(modifiers)
          || !Modifier.isStatic(modifiers) || !Modifier.isFinal(modifiers))
        throw new IOException("Invalid trusted console companion");
      consoleFailures.put(type, kinds[i]);
    }
  }
  private static void verifyOrigin(Class<?> type, ClassLoader loader, Path expected)
      throws Exception {
    var source = type.getProtectionDomain().getCodeSource();
    if (type.getClassLoader() != loader || source == null
        || !"file".equals(source.getLocation().getProtocol())
        || !Path.of(source.getLocation().toURI()).toRealPath().equals(expected))
      throw new IOException("Private class origin binding mismatch");
  }
  private int discovered, executed, passed, failed, skipped, aborted;
  private int containerFailures, eventErrors;
  private boolean complete;
  private final Set<String> registered = new TreeSet<>();
  private final Set<String> started = new TreeSet<>();
  private final Map<String, Map<String, Object>> caseReports = new LinkedHashMap<>();

  private void owner(TestIdentifier test) {
    if (plan == null || plan.getTestIdentifier(UniqueId.parse(test.getUniqueId())) != test)
      throw new SecurityException("Wrong JUnit test plan owner");
  }
  private void register(TestIdentifier test) {
    owner(test);
    if (!registered.add(test.getUniqueId()))
      eventErrors++;
    discovered = registered.size();
    gradingMetadata(test);
    if (observeAssertions)
      org.prairielearn.feedback.Gate.register(test.getUniqueId());
  }

  // Only data deliberately produced by a trusted check cross the feedback boundary.
  // Throwable messages, stack traces, arbitrary object.toString() and stdout do not.
  private static String bounded(String value) {
    return value.substring(0, Math.min(8192, value.length()));
  }

  private Map<String, Object> caseReport(TestIdentifier test) {
    return caseReports.computeIfAbsent(test.getUniqueId(), id -> {
      Map<String, Object> report = new HashMap<>();
      report.put("id", id);
      report.put("name", bounded(test.getDisplayName()));
      if (test.getSource().orElse(null) instanceof MethodSource method)
        report.put("test", method.getClassName() + "#" + method.getMethodName());
      return report;
    });
  }
  private final Map<String, Map<String, Object>> grading = new LinkedHashMap<>();
  private final Map<String, Double> classMaximums = new LinkedHashMap<>();
  private void gradingMetadata(TestIdentifier test) {
    double weight = 1;
    String name = test.getDisplayName(), description = "";
    for (var tag : test.getTags())
      if (tag.getName().startsWith("points="))
        weight = Double.parseDouble(tag.getName().substring(7));
    if (test.getSource().orElse(null) instanceof MethodSource source) {
      for (var annotation : source.getJavaMethod().getDeclaredAnnotations())
        if (annotation.annotationType().getName().equals("org.prairielearn.autograder.AutograderInfo")) {
          try {
            Class<?> type = annotation.annotationType();
            double points = (Double) type.getMethod("points").invoke(annotation);
            String label = (String) type.getMethod("name").invoke(annotation);
            if (points > 0) weight = points;
            if (!label.isEmpty()) name = label;
            description = (String) type.getMethod("description").invoke(annotation);
          } catch (ReflectiveOperationException invalid) {
            throw new IllegalStateException(invalid);
          }
        }
    }
    if (!Double.isFinite(weight) || weight < 0)
      throw new IllegalArgumentException("Invalid JUnit points");
    TestIdentifier owner = plan.getParent(test).orElse(null);
    while (owner != null && !(owner.getSource().orElse(null) instanceof ClassSource))
      owner = plan.getParent(owner).orElse(null);
    String ownerId = owner == null ? "" : owner.getUniqueId();
    grading.put(test.getUniqueId(), Map.of("weight", weight, "name", name,
        "description", description, "owner", ownerId));
  }
  private TestPlan plan;
  public synchronized void testPlanExecutionStarted(TestPlan plan) {
    try {
      engineCall("testPlanExecutionStarted");
      this.plan = Objects.requireNonNull(plan);
      phase = Phase.RUNNING;
      for (TestIdentifier root : plan.getRoots()) {
        Set<TestIdentifier> nodes = new HashSet<>(plan.getDescendants(root));
        nodes.add(root);
        for (TestIdentifier node : nodes)
          if (node.getSource().orElse(null) instanceof ClassSource)
            for (var tag : node.getTags())
              if (tag.getName().startsWith("maxpoints=")) {
                double maximum = Double.parseDouble(tag.getName().substring(10));
                if (!Double.isFinite(maximum) || maximum < 0)
                  throw new IllegalArgumentException("Invalid JUnit maxpoints");
                classMaximums.put(node.getUniqueId(), maximum);
              }
      }
      if (this.complete || !registered.isEmpty())
        eventErrors++;
      for (TestIdentifier root : plan.getRoots()) {
        if (root.isTest())
          register(root);
        for (TestIdentifier test : plan.getDescendants(root))
          if (test.isTest())
            register(test);
      }

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  public synchronized void dynamicTestRegistered(TestIdentifier test) {
    try {
      engineCall("dynamicTestRegistered");
      owner(test);
      if (test.isTest())
        register(test);

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  public synchronized void executionStarted(TestIdentifier test) {
    try {
      engineCall("executionStarted");
      owner(test);
      if (test.isTest()) {
        if (!registered.contains(test.getUniqueId()) || !started.add(test.getUniqueId()))
          eventErrors++;
        if (observeAssertions)
          org.prairielearn.feedback.Gate.start(test.getUniqueId());
        executed++;
      }

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  public synchronized void executionSkipped(TestIdentifier test, String reason) {
    try {
      engineCall("executionSkipped");
      owner(test);
      Set<TestIdentifier> skippedTests = new HashSet<>();
      if (test.isTest())
        skippedTests.add(test);
      else if (plan != null)
        for (TestIdentifier child : plan.getDescendants(test))
          if (child.isTest())
            skippedTests.add(child);
      for (TestIdentifier child : skippedTests)
        if (outcomes.putIfAbsent(child.getUniqueId(), "skipped") == null)
          skipped++;

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  public synchronized void executionFinished(TestIdentifier test, TestExecutionResult result) {
    try {
      engineCall("executionFinished");
      owner(test);
      if (!test.isTest()) {
        if (result.getStatus() == TestExecutionResult.Status.FAILED)
          containerFailures++;
        else if (result.getStatus() == TestExecutionResult.Status.SUCCESSFUL)
          successfulContainers.add(test.getUniqueId());
        return;
      }
      String status = result.getStatus().name().toLowerCase(Locale.ROOT);
      if (!registered.contains(test.getUniqueId()) || !started.contains(test.getUniqueId())
          || outcomes.putIfAbsent(test.getUniqueId(), status) != null)
        eventErrors++;
      Map<String, Object> report = caseReport(test);
      report.put("status",
          result.getStatus() == TestExecutionResult.Status.SUCCESSFUL ? "passed" : "failed");
      if (observeAssertions) {
        List<Map<String, String>> checks = new ArrayList<>();
        Set<String> publicFields = Set.of("site", "property", "availability", "expected", "actual",
            "delta", "differenceIndex", "differenceExpected", "differenceActual", "differenceLine",
            "differenceColumn", "delegated");
        for (var check : org.prairielearn.feedback.Gate.finish(test.getUniqueId())) {
          Map<String, String> safe = new LinkedHashMap<>();
          for (var entry : check.entrySet())
            if (publicFields.contains(entry.getKey()))
              safe.put(entry.getKey(), entry.getValue());
          checks.add(Map.copyOf(safe));
        }
        report.put("checks", List.copyOf(checks));
      }
      if (result.getStatus() == TestExecutionResult.Status.FAILED) {
        String kind = result.getThrowable().map(this::failureKind).orElse("runtime");
        failures.put(test.getUniqueId(), kind);
      }
      switch (result.getStatus()) {
        case SUCCESSFUL:
          passed++;
          break;
        case FAILED:
          failed++;
          break;
        case ABORTED:
          aborted++;
          break;
      }

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  public synchronized void testPlanExecutionFinished(TestPlan plan) {
    try {
      engineCall("testPlanExecutionFinished");
      if (this.plan != plan || complete) {
        integrityFailure = true;
        throw new SecurityException("Wrong JUnit plan owner");
      }
      complete = true;
      phase = Phase.FINISHED;

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }
  private String failureKind(Throwable failure) {
    Set<Throwable> wrappers = Collections.newSetFromMap(new IdentityHashMap<>());
    for (int depth = 0; ; depth++) {
      // Только reflection и известные VM initialization wrappers, не произвольные causes.
      if (depth == 16 || !wrappers.add(failure))
        return "infrastructure";
      Throwable cause = null;
      if (failure instanceof InvocationTargetException
          || failure.getClass() == ExceptionInInitializerError.class)
        cause = failure.getCause();
      else if (failure.getClass() == NoClassDefFoundError.class) {
        Throwable candidate = failure.getCause();
        if (candidate != null && candidate.getClass() == ExceptionInInitializerError.class)
          cause = candidate;
      }
      if (cause == null)
        break;
      failure = cause;
    }
    String consoleKind = consoleFailures.get(failure.getClass());
    if (consoleKind != null)
      return consoleKind;
    if (failure instanceof AssertionError) {
      try {
        if (studentAssertionOrigin(failure))
          return "runtime";
      } catch (Exception | LinkageError brokenBinding) {
        return "infrastructure";
      }
      return "wrong-answer";
    }
    if (failure instanceof ReflectiveOperationException)
      return "wrong-answer";
    for (StackTraceElement frame : failure.getStackTrace())
      for (String name : studentClasses)
        if (frame.getClassName().equals(name) || frame.getClassName().startsWith(name + "$"))
          return "runtime";
    return "infrastructure";
  }
  public synchronized void reportingEntryPublished(TestIdentifier test, ReportEntry entry) {
    try {
      engineCall("reportingEntryPublished");
      owner(test);
      if (test.isTest() && "implementation".equals(submissionMode)) {
        if (!registered.contains(test.getUniqueId()) || !started.contains(test.getUniqueId())
            || outcomes.containsKey(test.getUniqueId())) {
          integrityFailure = true;
          throw new SecurityException("Reporting requires an active registered leaf");
        }
        Map<String, Object> report = caseReport(test);
        Map<String, String> values = entry.getKeyValuePairs();
        for (String key : List.of("expected", "actual"))
          if (values.containsKey(key))
            report.put(key, bounded(values.get(key)));
      }

    } catch (RuntimeException | Error invalid) {
      if (this == authorizedListener) integrityFailure = true;
      throw invalid;
    }
  }

  private synchronized Map<String, Object> retire(boolean observe) {
    RuntimeIdentity.requireMain();
    if (this != authorizedListener || phase != Phase.FINISHED || integrityFailure || !complete)
      throw new SecurityException("JUnit listener integrity failed");
    phase = Phase.RETIRED;
    authorizedListener = null;
    Map<String, Object> feedback = new HashMap<>();
    feedback.put("feedbackProtocolVersion", observe ? 2 : 1);
    feedback.put("complete", eventErrors == 0);
    feedback.put("verifiedOutcomes", Map.copyOf(outcomes));
    feedback.put("successfulContainers", List.copyOf(successfulContainers));
    feedback.put("cases", caseReports.values().stream().map(Map::copyOf).toList());
    feedback.put("failureKinds", Map.copyOf(failures));
    feedback.put("grading", Map.copyOf(grading));
    feedback.put("classMaximums", Map.copyOf(classMaximums));
    feedback.put("containerFailures", containerFailures);
    return Map.copyOf(feedback);
  }

  public static void main(String[] args) throws Exception {
    RuntimeIdentity.bootstrap(PlatformJUnitAdapter.class);
    Path parameterFile = Path.of(args[0]);
    JSONObject params;
    try (Reader reader = Files.newBufferedReader(parameterFile)) {
      params = (JSONObject) new JSONParser().parse(reader);
    }
    Files.delete(parameterFile);
    byte[] reportKey = HexFormat.of().parseHex((String) params.remove("report_key"));
    try {
      if (reportKey.length != 32) throw new IOException("Invalid result authentication key");
      RuntimeIdentity.bind(params.remove("runtime_modules"));
      if (!(params.get("observe_assertions") instanceof Boolean observe))
        throw new IOException("Missing private assertion mode");
      if (observe)
        org.prairielearn.feedback.Gate.bind();
      String feedbackFile = (String) params.get("feedback_file");
      Object[] classes = ((JSONArray) params.get("test_classes")).toArray();
      String[] testClasses = Arrays.copyOf(classes, classes.length, String[].class);
      PlatformJUnitAdapter listener = new PlatformJUnitAdapter();
      listener.bindConsoleSupport(params.get("trusted_console_support_root"));
      listener.bindStudentOrigin(params);
      if (observe != "implementation".equals(listener.submissionMode))
        throw new IOException("Private assertion mode mismatch");
      listener.observeAssertions = observe;
      listener.bindReportingOrigin(params);
      Launcher launcher = LauncherFactory.create();
      launcher.registerTestExecutionListeners(listener,
          new LegacyXmlReportGeneratingListener(Path.of((String) params.get("reports_dir")),
              new PrintWriter(System.err)));
      var request = LauncherDiscoveryRequestBuilder.request().selectors(
          Arrays.stream(testClasses).map(name -> selectClass(name)).toList()).build();
      synchronized (listener) {
        authorizedListener = listener;
        listener.phase = Phase.LAUNCHING;
      }
      launcher.execute(request);
      Map<String, Object> feedback = listener.retire(observe);
      byte[] payload = JSONValue.toJSONString(feedback).getBytes(StandardCharsets.UTF_8);
      Mac authentication = Mac.getInstance("HmacSHA256");
      authentication.init(new SecretKeySpec(reportKey, "HmacSHA256"));
      Files.write(Path.of(feedbackFile), payload);
      Files.writeString(Path.of(feedbackFile + ".signature"),
          HexFormat.of().formatHex(authentication.doFinal(payload)));
    } finally {
      authorizedListener = null;
      Arrays.fill(reportKey, (byte) 0);
    }
    System.exit(0);
  }
}
