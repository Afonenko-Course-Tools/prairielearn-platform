package org.prairielearn.feedback.internal;

import java.io.IOException;
import java.lang.module.ModuleDescriptor;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.util.*;
import java.util.stream.Collectors;
import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import org.junit.platform.engine.TestEngine;

/** Неизменные идентичности закрытого runtime; не загружает State и не хранит listener. */
public final class RuntimeIdentity {
  private RuntimeIdentity() {}
  private static final StackWalker WALK = StackWalker.getInstance(Set.of(
      StackWalker.Option.RETAIN_CLASS_REFERENCE, StackWalker.Option.SHOW_HIDDEN_FRAMES,
      StackWalker.Option.SHOW_REFLECT_FRAMES));
  private static final String ADAPTER = "org.prairielearn.feedback.PlatformJUnitAdapter";
  private static final Map<String, String> ANCHORS = Map.ofEntries(
      Map.entry("org.junit.jupiter.api", "org.junit.jupiter.api.Assertions"),
      Map.entry("org.junit.jupiter.engine", "org.junit.jupiter.engine.JupiterTestEngine"),
      Map.entry("org.junit.jupiter.params", "org.junit.jupiter.params.ParameterizedTest"),
      Map.entry("org.junit.platform.commons", "org.junit.platform.commons.JUnitException"),
      Map.entry("org.junit.platform.engine", "org.junit.platform.engine.TestEngine"),
      Map.entry("org.junit.platform.launcher", "org.junit.platform.launcher.Launcher"),
      Map.entry("org.junit.platform.reporting", "org.junit.platform.reporting.legacy.xml.LegacyXmlReportGeneratingListener"),
      Map.entry("org.opentest4j", "org.opentest4j.AssertionFailedError"),
      Map.entry("org.apiguardian.api", "org.apiguardian.api.API"),
      Map.entry("org.opentest4j.reporting.tooling.spi", "org.opentest4j.reporting.tooling.spi.htmlreport.Contributor"));
  private static final Set<String> INVOCATION_MODULES = Set.of("org.junit.jupiter.api",
      "org.junit.jupiter.engine", "org.junit.jupiter.params", "org.junit.platform.commons",
      "org.junit.platform.engine", "org.junit.platform.launcher");
  private static boolean entered;
  private static Class<?> adapter;
  private static Thread mainThread;
  private static volatile Map<String, Module> modules = Map.of();
  private static volatile Map<String, Class<?>> anchors = Map.of();
  private static volatile Map<String, Class<?>> types = Map.of();
  private static volatile Set<Class<?>> dispatchHosts = Set.of();
  private static volatile Set<Class<?>> invocationHosts = Set.of();

  public static synchronized void bootstrap(Class<?> entry) throws Exception {
    List<StackWalker.StackFrame> frames = frames();
    if (entered || entry.getModule() != RuntimeIdentity.class.getModule()
        || !entry.getName().equals(ADAPTER) || entry.getClassLoader() != ClassLoader.getSystemClassLoader()
        || !entry.getModule().isNamed() || entry.getModule().getDescriptor().isAutomatic()
        || entry.getModule().getDescriptor().isOpen() || frames.isEmpty())
      throw new SecurityException("Invalid original launcher entry");
    StackWalker.StackFrame last = frames.getLast();
    long mains = frames.stream().filter(f -> f.getDeclaringClass() == entry
        && f.getMethodName().equals("main") && f.getDescriptor().equals("([Ljava/lang/String;)V")).count();
    if (last.getDeclaringClass() != entry || !last.getMethodName().equals("main")
        || !last.getDescriptor().equals("([Ljava/lang/String;)V") || mains != 1)
      throw new SecurityException("Launcher requires original VM main");
    entered = true;
    adapter = entry;
    mainThread = Thread.currentThread();
    Path root = origin(entry);
    Path location = Path.of(ModuleLayer.boot().configuration().findModule(entry.getModule().getName())
        .orElseThrow().reference().location().orElseThrow()).toAbsolutePath().normalize();
    if (!Files.isDirectory(root) || !root.equals(origin(RuntimeIdentity.class))
        || Files.isSymbolicLink(location) || !location.equals(location.toRealPath())
        || !root.equals(location))
      throw new SecurityException("Invalid observer origin");
    observerClosure();
  }

  public static void requireMain() {
    if (!entered || Thread.currentThread() != mainThread)
      throw new SecurityException("Missing original launcher thread");
    List<StackWalker.StackFrame> frames = frames();
    StackWalker.StackFrame last = frames.getLast();
    if (last.getDeclaringClass() != adapter || !last.getMethodName().equals("main")
        || !last.getDescriptor().equals("([Ljava/lang/String;)V")
        || frames.stream().filter(f -> f.getDeclaringClass() == adapter
            && f.getMethodName().equals("main")).count() != 1)
      throw new SecurityException("Missing original launcher main");
  }

  public static synchronized void bind(Object value) throws Exception {
    requireMain();
    if (!modules.isEmpty() || !(value instanceof JSONArray rows) || rows.size() != ANCHORS.size())
      throw new SecurityException("Invalid private runtime binding");
    Map<String, Module> bound = new HashMap<>();
    Map<String, Class<?>> classes = new HashMap<>();
    for (Object item : rows) {
      if (!(item instanceof JSONObject row) || !(row.get("module") instanceof String name)
          || !(row.get("version") instanceof String version)
          || !(row.get("path") instanceof String path)
          || !(row.get("sha256") instanceof String sha) || !sha.matches("[0-9a-f]{64}")
          || !(row.get("descriptor") instanceof JSONObject receipt) || !ANCHORS.containsKey(name)
          || bound.containsKey(name))
        throw new SecurityException("Invalid private module receipt");
      Module module = ModuleLayer.boot().findModule(name).orElseThrow();
      ModuleDescriptor descriptor = module.getDescriptor();
      if (!module.isNamed() || descriptor.isAutomatic() || descriptor.isOpen()
          || module.getLayer() != ModuleLayer.boot()
          || module.getClassLoader() != ClassLoader.getSystemClassLoader()
          || !descriptor.rawVersion().orElse("").equals(version))
        throw new SecurityException("Invalid runtime module identity");
      Path expected = safeFile(Path.of(path));
      Path location = safeFile(Path.of(ModuleLayer.boot().configuration().findModule(name)
          .orElseThrow().reference().location().orElseThrow()));
      Class<?> anchor = Class.forName(module, ANCHORS.get(name));
      if (anchor == null || anchor.getModule() != module
          || anchor.getClassLoader() != ClassLoader.getSystemClassLoader()
          || !expected.equals(location) || !expected.equals(origin(anchor))
          || !Files.getOwner(expected).equals(Files.getOwner(origin(adapter))))
        throw new SecurityException("Runtime origin differs from immutable copy");
      descriptor(descriptor, receipt);
      bound.put(name, module);
      classes.put(name, anchor);
    }
    if (!bound.keySet().equals(ANCHORS.keySet()))
      throw new SecurityException("Runtime module inventory mismatch");
    modules = Map.copyOf(bound);
    anchors = Map.copyOf(classes);
    for (String[] target : new String[][] {
        {"org.junit.jupiter.api", "org.junit.jupiter.api"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical"}}) {
      Module module = modules.get(target[0]);
      for (Module viewer : List.of(adapter.getModule(), ClassLoader.getSystemClassLoader().getUnnamedModule(),
                                  modules.get("org.junit.platform.commons"))) {
        if (module.isOpen(target[1], viewer)
            || target[0].equals("org.junit.jupiter.engine") && module.isExported(target[1], viewer))
          throw new SecurityException("Runtime lifecycle package is exposed");
      }
    }
    Map<String, Class<?>> linked = new HashMap<>();
    for (String[] entry : new String[][] {
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.CompositeTestExecutionListener"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.ExecutionListenerAdapter"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.NodeTestTask"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.ForkJoinPoolHierarchicalTestExecutorService$ExclusiveTask"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InvocationInterceptorChain$InterceptedInvocation"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.AbstractExtensionContext"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.MethodExtensionContext"},
        {"org.junit.jupiter.api", "org.junit.jupiter.api.AssertTimeoutPreemptively"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.CompositeEngineExecutionListener"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.ForkJoinPoolHierarchicalTestExecutorService"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.ThrowableCollector"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.Node"},
        {"org.junit.platform.commons", "org.junit.platform.commons.util.CollectionUtils"},
        {"org.junit.platform.commons", "org.junit.platform.commons.util.ReflectionUtils"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InvocationInterceptorChain"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.MethodInvocation"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestFactoryTestDescriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestMethodTestDescriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestTemplateTestDescriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestTemplateInvocationTestDescriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.DynamicTestTestDescriptor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.extension.SeparateThreadTimeoutInvocation"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.extension.SameThreadTimeoutInvocation"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.extension.TimeoutInvocationFactory"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.extension.DefaultTestReporter"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.EngineExecutionOrchestrator"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.DefaultLauncher"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.DefaultLauncherSession"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.SessionPerRequestLauncher"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.IterationOrder$1"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.IterationOrder$2"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.NodeTestTask$DefaultDynamicTestExecutor"},
        {"org.junit.platform.engine", "org.junit.platform.engine.support.hierarchical.SameThreadHierarchicalTestExecutorService"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker$ReflectiveInterceptorCall"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker$ReflectiveInterceptorCall$VoidMethodInterceptorCall"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.execution.InvocationInterceptorChain$ValidatingInvocation"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestTemplateTestDescriptor$TestTemplateExecutor"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.TestMethodTestDescriptor$1"},
        {"org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor"},
        {"org.junit.platform.launcher", "org.junit.platform.launcher.core.EngineExecutionOrchestrator$1"}}) {
      Module expected = modules.get(entry[0]);
      Class<?> type = Class.forName(expected, entry[1]);
      if (type == null || type.getModule() != expected
          || type.getClassLoader() != ClassLoader.getSystemClassLoader()
          || !origin(type).equals(origin(anchors.get(entry[0]))))
        throw new SecurityException("Invalid pinned runtime anchor");
      linked.put(entry[1], type);
    }
    types = Map.copyOf(linked);
    Set<Class<?>> dispatch = new HashSet<>();
    for (String name : List.of(
        "org.junit.platform.launcher.core.CompositeTestExecutionListener",
        "org.junit.platform.launcher.core.CompositeEngineExecutionListener",
        "org.junit.platform.launcher.core.ExecutionListenerAdapter",
        "org.junit.platform.engine.support.hierarchical.NodeTestTask",
        "org.junit.platform.engine.support.hierarchical.ForkJoinPoolHierarchicalTestExecutorService",
        "org.junit.platform.engine.support.hierarchical.ThrowableCollector",
        "org.junit.platform.engine.support.hierarchical.Node",
        "org.junit.platform.commons.util.CollectionUtils",
        "org.junit.jupiter.engine.descriptor.TestFactoryTestDescriptor",
        "org.junit.platform.launcher.core.EngineExecutionOrchestrator",
        "org.junit.platform.launcher.core.EngineExecutionOrchestrator$1",
        "org.junit.platform.launcher.core.DefaultLauncher",
        "org.junit.platform.launcher.core.DefaultLauncherSession",
        "org.junit.platform.launcher.core.SessionPerRequestLauncher",
        "org.junit.platform.launcher.core.IterationOrder$1",
        "org.junit.platform.launcher.core.IterationOrder$2",
        "org.junit.platform.engine.support.hierarchical.NodeTestTask$DefaultDynamicTestExecutor",
        "org.junit.platform.engine.support.hierarchical.SameThreadHierarchicalTestExecutorService"))
      dispatch.add(Objects.requireNonNull(linked.get(name)));
    dispatchHosts = Set.copyOf(dispatch);
    Set<Class<?>> invocation = new HashSet<>(dispatch);
    for (String name : List.of(
        "org.junit.jupiter.engine.execution.InvocationInterceptorChain",
        "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker",
        "org.junit.jupiter.engine.execution.MethodInvocation",
        "org.junit.jupiter.engine.descriptor.TestMethodTestDescriptor",
        "org.junit.jupiter.engine.descriptor.TestTemplateTestDescriptor",
        "org.junit.jupiter.engine.descriptor.TestTemplateInvocationTestDescriptor",
        "org.junit.jupiter.engine.descriptor.DynamicTestTestDescriptor",
        "org.junit.jupiter.engine.descriptor.AbstractExtensionContext",
        "org.junit.jupiter.engine.extension.DefaultTestReporter",
        "org.junit.jupiter.engine.extension.SeparateThreadTimeoutInvocation",
        "org.junit.jupiter.engine.extension.SameThreadTimeoutInvocation",
        "org.junit.jupiter.engine.extension.TimeoutInvocationFactory",
        "org.junit.platform.commons.util.ReflectionUtils",
        "org.junit.jupiter.api.AssertTimeoutPreemptively",
        "org.junit.platform.engine.support.hierarchical.ForkJoinPoolHierarchicalTestExecutorService$ExclusiveTask",
        "org.junit.jupiter.engine.execution.InvocationInterceptorChain$InterceptedInvocation",
        "org.junit.jupiter.engine.execution.InvocationInterceptorChain$ValidatingInvocation",
        "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker$ReflectiveInterceptorCall",
        "org.junit.jupiter.engine.execution.InterceptingExecutableInvoker$ReflectiveInterceptorCall$VoidMethodInterceptorCall",
        "org.junit.jupiter.engine.descriptor.TestTemplateTestDescriptor$TestTemplateExecutor",
        "org.junit.jupiter.engine.descriptor.TestMethodTestDescriptor$1",
        "org.junit.jupiter.engine.descriptor.ClassBasedTestDescriptor"))
      invocation.add(Objects.requireNonNull(linked.get(name)));
    invocationHosts = Set.copyOf(invocation);
    observerClosure();
    List<Class<? extends TestEngine>> providers = ServiceLoader.load(TestEngine.class).stream()
        .map(ServiceLoader.Provider::type).toList();
    if (providers.size() != 1 || providers.getFirst() != anchors.get("org.junit.jupiter.engine"))
      throw new SecurityException("Unexpected JUnit engine provider");
  }

  private static void observerClosure() {
    Module observer = RuntimeIdentity.class.getModule();
    Module unnamed = ClassLoader.getSystemClassLoader().getUnnamedModule();
    boolean expectedInternalOpen = false;
    ModuleDescriptor own = observer.getDescriptor();
    Set<String> ownRequires = own.requires().stream().map(r -> r.modifiers().stream()
        .map(m -> m.name().toLowerCase(Locale.ROOT)).sorted().collect(Collectors.joining(" ")) + ":" + r.name())
        .collect(Collectors.toSet());
    if (!observer.isNamed() || !observer.getName().equals("org.prairielearn.feedback")
        || observer.getLayer() != ModuleLayer.boot() || own.isAutomatic() || own.isOpen()
        || !ownRequires.equals(Set.of("mandated:java.base", "transitive:org.junit.jupiter.api",
            "transitive:org.junit.platform.launcher", ":org.junit.platform.reporting", ":json.simple"))
        || own.exports().size() != 1 || !own.exports().iterator().next().source().equals("org.prairielearn.feedback")
        || own.exports().iterator().next().isQualified()
        || !own.uses().equals(Set.of("org.junit.platform.engine.TestEngine"))
        || own.provides().size() != 1
        || !own.provides().iterator().next().service().equals("org.junit.jupiter.api.extension.Extension")
        || !own.provides().iterator().next().providers().equals(List.of("org.prairielearn.feedback.internal.Scope"))
        || !own.opens().isEmpty()
        || observer.isExported("org.prairielearn.feedback.internal", unnamed))
      throw new SecurityException("Observer internal package is exposed");
    Set<Module> viewers = new HashSet<>(ModuleLayer.boot().modules());
    viewers.remove(observer);
    viewers.add(unnamed);
    for (Module viewer : viewers)
      if (observer.isOpen("org.prairielearn.feedback", viewer)
          || observer.isOpen("org.prairielearn.feedback.internal", viewer)
              != (expectedInternalOpen && viewer == unnamed)
          || observer.isExported("org.prairielearn.feedback.internal", viewer))
        throw new SecurityException("Observer effective closure differs");
  }
  private static Path safeFile(Path path) throws IOException {
    Path absolute = path.toAbsolutePath().normalize();
    if (Files.isSymbolicLink(absolute) || !Files.isRegularFile(absolute, LinkOption.NOFOLLOW_LINKS)
        || !absolute.equals(absolute.toRealPath()))
      throw new IOException("Unsafe runtime artifact path");
    Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(absolute);
    if (permissions.contains(PosixFilePermission.GROUP_WRITE)
        || permissions.contains(PosixFilePermission.OTHERS_WRITE))
      throw new IOException("Writable runtime artifact");
    return absolute;
  }
  private static Path origin(Class<?> owner) throws Exception {
    var source = owner.getProtectionDomain().getCodeSource();
    if (source == null || !"file".equals(source.getLocation().getProtocol()))
      throw new SecurityException("Missing runtime file origin");
    Path path = Path.of(source.getLocation().toURI()).toAbsolutePath().normalize();
    if (Files.isSymbolicLink(path) || !path.equals(path.toRealPath()))
      throw new SecurityException("Unsafe runtime origin");
    return path;
  }
  private static Set<String> strings(Object value) {
    if (!(value instanceof JSONArray list))
      throw new SecurityException("Missing descriptor directive receipt");
    Set<String> result = new HashSet<>();
    for (Object entry : list)
      if (!(entry instanceof String text) || !result.add(text))
        throw new SecurityException("Invalid descriptor directive receipt");
    return result;
  }
  private static String qualified(String source, Set<String> targets) {
    return source + " to " + targets.stream().sorted().collect(Collectors.joining(","));
  }
  private static void descriptor(ModuleDescriptor actual, JSONObject receipt) {
    Set<String> requires = new HashSet<>();
    Object rawRequires = receipt.get("requires");
    if (!(rawRequires instanceof JSONArray list))
      throw new SecurityException("Missing requires receipt");
    for (Object item : list) {
      if (!(item instanceof JSONObject row) || !(row.get("module") instanceof String name))
        throw new SecurityException("Invalid requires receipt");
      if (!requires.add(strings(row.get("modifiers")).stream().sorted().collect(Collectors.joining(" ")) + ":" + name))
        throw new SecurityException("Duplicate requires receipt");
    }
    Set<String> actualRequires = actual.requires().stream().map(r -> r.modifiers().stream()
        .map(m -> m.name().toLowerCase(Locale.ROOT)).sorted().collect(Collectors.joining(" ")) + ":" + r.name())
        .collect(Collectors.toSet());
    Set<String> exports = actual.exports().stream().map(e -> e.isQualified()
        ? qualified(e.source(), e.targets()) : e.source()).collect(Collectors.toSet());
    Set<String> opens = actual.opens().stream().map(e -> e.isQualified()
        ? qualified(e.source(), e.targets()) : e.source()).collect(Collectors.toSet());
    Set<String> provides = actual.provides().stream().map(p -> p.service() + " with "
        + p.providers().stream().sorted().collect(Collectors.joining(","))).collect(Collectors.toSet());
    if (!requires.equals(actualRequires) || !strings(receipt.get("exports")).equals(exports)
        || !strings(receipt.get("opens")).equals(opens) || !strings(receipt.get("uses")).equals(actual.uses())
        || !strings(receipt.get("provides")).equals(provides))
      throw new SecurityException("Runtime descriptor differs from qualified receipt");
  }
  public static List<StackWalker.StackFrame> frames() { return WALK.walk(s -> s.toList()); }
  public static boolean invocation(Class<?> type) {
    Module module = type.getModule();
    return module.isNamed() && type.getClassLoader() == ClassLoader.getSystemClassLoader()
        && INVOCATION_MODULES.contains(module.getName()) && modules.get(module.getName()) == module;
  }
  // Host разрешает только посредника; методные опоры проверяются отдельно для операции.
  public static boolean intermediary(Class<?> owner, boolean invocationPath) {
    if (owner.getClassLoader() == null)
      return true;
    if (!invocation(owner))
      return false;
    if (!owner.isHidden())
      return true;
    Class<?> host = owner.getNestHost();
    return owner.getModule() == host.getModule()
        && owner.getClassLoader() == host.getClassLoader()
        && (invocationPath ? invocationHosts : dispatchHosts).contains(host);
  }
  private record Dispatch(String descriptor, String synthetic, String syntheticDescriptor,
                          String engineDescriptor) {}
  // N0 actual7: Composite/ExecutionListenerAdapter Code и BootstrapMethods, без callback BCI.
  private static final Map<String, Dispatch> EVENTS = Map.of(
      "dynamicTestRegistered", new Dispatch("(Lorg/junit/platform/launcher/TestIdentifier;)V",
          "lambda$dynamicTestRegistered$0", "(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/launcher/TestExecutionListener;)V",
          "(Lorg/junit/platform/engine/TestDescriptor;)V"),
      "executionStarted", new Dispatch("(Lorg/junit/platform/launcher/TestIdentifier;)V",
          "lambda$executionStarted$6", "(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/launcher/TestExecutionListener;)V",
          "(Lorg/junit/platform/engine/TestDescriptor;)V"),
      "executionSkipped", new Dispatch("(Lorg/junit/platform/launcher/TestIdentifier;Ljava/lang/String;)V",
          "lambda$executionSkipped$2", "(Lorg/junit/platform/launcher/TestIdentifier;Ljava/lang/String;Lorg/junit/platform/launcher/TestExecutionListener;)V",
          "(Lorg/junit/platform/engine/TestDescriptor;Ljava/lang/String;)V"),
      "executionFinished", new Dispatch("(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/engine/TestExecutionResult;)V",
          "lambda$executionFinished$10", "(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/engine/TestExecutionResult;Lorg/junit/platform/launcher/TestExecutionListener;)V",
          "(Lorg/junit/platform/engine/TestDescriptor;Lorg/junit/platform/engine/TestExecutionResult;)V"),
      "testPlanExecutionStarted", new Dispatch("(Lorg/junit/platform/launcher/TestPlan;)V",
          "lambda$testPlanExecutionStarted$12", "(Lorg/junit/platform/launcher/TestPlan;Lorg/junit/platform/launcher/TestExecutionListener;)V", ""),
      "testPlanExecutionFinished", new Dispatch("(Lorg/junit/platform/launcher/TestPlan;)V",
          "lambda$testPlanExecutionFinished$14", "(Lorg/junit/platform/launcher/TestPlan;Lorg/junit/platform/launcher/TestExecutionListener;)V", ""),
      "reportingEntryPublished", new Dispatch("(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/engine/reporting/ReportEntry;)V",
          "lambda$reportingEntryPublished$16", "(Lorg/junit/platform/launcher/TestIdentifier;Lorg/junit/platform/engine/reporting/ReportEntry;Lorg/junit/platform/launcher/TestExecutionListener;)V",
          "(Lorg/junit/platform/engine/TestDescriptor;Lorg/junit/platform/engine/reporting/ReportEntry;)V"));
  private static boolean frame(StackWalker.StackFrame actual, Class<?> owner, String method, String descriptor) {
    return actual.getDeclaringClass() == owner && actual.getMethodName().equals(method)
        && actual.getDescriptor().equals(descriptor);
  }
  private static int find(List<StackWalker.StackFrame> frames, int start, Class<?> owner,
                          String method, String descriptor) {
    for (int i = Math.max(0, start); i < frames.size(); i++)
      if (frame(frames.get(i), owner, method, descriptor)) return i;
    return -1;
  }
  private static boolean originalMain(List<StackWalker.StackFrame> frames) {
    return entered && Thread.currentThread() == mainThread && !frames.isEmpty()
        && frame(frames.getLast(), adapter, "main", "([Ljava/lang/String;)V")
        && frames.stream().filter(f -> f.getDeclaringClass() == adapter
            && f.getMethodName().equals("main")).count() == 1;
  }
  private static boolean hidden(StackWalker.StackFrame actual, Class<?> host, String method) {
    Class<?> owner = actual.getDeclaringClass();
    return owner.isHidden() && owner.getNestHost() == host
        && owner.getModule() == host.getModule() && owner.getClassLoader() == host.getClassLoader()
        && actual.getMethodName().equals(method) && actual.getDescriptor().equals("()Ljava/lang/Object;");
  }
  private static boolean apiWorkerAt(List<StackWalker.StackFrame> frames, int index) {
    Class<?> boundary = type("org.junit.jupiter.api", "org.junit.jupiter.api.AssertTimeoutPreemptively");
    // Actual lambda$submitTask$3 BCI8 вызывает supplier.get; hidden Callable создан submitTask.
    if (index < 0 || index + 2 >= frames.size()
        || !frame(frames.get(index), boundary, "lambda$submitTask$3",
            "(Ljava/util/concurrent/atomic/AtomicReference;Lorg/junit/jupiter/api/function/ThrowingSupplier;)Ljava/lang/Object;")
        || frames.get(index).getByteCodeIndex() != 8
        || !hidden(frames.get(index + 1), boundary, "call")
        || !frame(frames.get(index + 2), java.util.concurrent.FutureTask.class, "run", "()V"))
      return false;
    for (int i = index + 2; i < frames.size(); i++)
      if (frames.get(i).getDeclaringClass().getClassLoader() != null)
        return false;
    return true;
  }
  private static boolean apiWorker(List<StackWalker.StackFrame> frames, int start) {
    Class<?> boundary = type("org.junit.jupiter.api", "org.junit.jupiter.api.AssertTimeoutPreemptively");
    int index = find(frames, start, boundary, "lambda$submitTask$3",
        "(Ljava/util/concurrent/atomic/AtomicReference;Lorg/junit/jupiter/api/function/ThrowingSupplier;)Ljava/lang/Object;");
    return apiWorkerAt(frames, index);
  }
  public static boolean timeoutWorker(boolean executable, List<StackWalker.StackFrame> frames, int start) {
    Class<?> boundary = type("org.junit.jupiter.api", "org.junit.jupiter.api.AssertTimeoutPreemptively");
    int index = start;
    if (executable) {
      if (index >= frames.size()) return false;
      StackWalker.StackFrame call = frames.get(index++);
      if (!(frame(call, boundary, "lambda$assertTimeoutPreemptively$0",
                    "(Lorg/junit/jupiter/api/function/Executable;)Ljava/lang/Object;")
            || frame(call, boundary, "lambda$assertTimeoutPreemptively$1",
                    "(Lorg/junit/jupiter/api/function/Executable;)Ljava/lang/Object;"))
          || call.getByteCodeIndex() != 1)
        return false;
      if (index < frames.size() && hidden(frames.get(index), boundary, "get")) index++;
    }
    return apiWorkerAt(frames, index);
  }
  private static boolean platformWorker(List<StackWalker.StackFrame> frames, int start) {
    int node = find(frames, start, type("org.junit.platform.engine",
        "org.junit.platform.engine.support.hierarchical.NodeTestTask"), "execute", "()V");
    return node >= 0 && find(frames, node + 1, type("org.junit.platform.engine",
        "org.junit.platform.engine.support.hierarchical.ForkJoinPoolHierarchicalTestExecutorService$ExclusiveTask"),
        "exec", "()Z") > node;
  }
  private static void allowedFrames(List<StackWalker.StackFrame> frames, boolean invocationPath,
                                     Set<Class<?>> reportingCallers) {
    for (int i = 0; i < frames.size(); i++) {
      StackWalker.StackFrame call = frames.get(i);
      Class<?> owner = call.getDeclaringClass();
      if (owner.getModule() == RuntimeIdentity.class.getModule() || intermediary(owner, invocationPath)
          || reportingCallers.contains(owner))
        continue;
      if (owner.isHidden() && i > 0) {
        Class<?> host = owner.getNestHost();
        StackWalker.StackFrame previous = frames.get(i - 1);
        if (reportingCallers.contains(host) && previous.getDeclaringClass() == host
            && previous.getMethodName().startsWith("lambda$")
            && owner.getClassLoader() == host.getClassLoader() && owner.getModule() == host.getModule())
          continue;
      }
      throw new SecurityException("Untrusted JUnit lifecycle intermediary");
    }
  }
  private static void callback(List<StackWalker.StackFrame> frames, String event,
                                Set<Class<?>> reportingCallers) {
    Dispatch dispatch = EVENTS.get(event);
    if (dispatch == null) throw new SecurityException("Unknown JUnit callback");
    boolean reporting = event.equals("reportingEntryPublished");
    allowedFrames(frames, reporting, reporting ? reportingCallers : Set.of());
    Class<?> composite = type("org.junit.platform.launcher", "org.junit.platform.launcher.core.CompositeTestExecutionListener");
    int first = 0;
    while (first < frames.size() && frames.get(first).getDeclaringClass().getModule() == RuntimeIdentity.class.getModule()) first++;
    int notify = find(frames, first + 1, composite, "notifyEach",
        "(Ljava/util/List;Lorg/junit/platform/launcher/core/IterationOrder;Ljava/util/function/Consumer;Ljava/util/function/Supplier;)V");
    int compositeEvent = find(frames, notify + 1, composite, event, dispatch.descriptor());
    if (first == frames.size() || !frame(frames.get(first), composite, dispatch.synthetic(), dispatch.syntheticDescriptor())
        || notify < first || compositeEvent < notify)
      throw new SecurityException("Missing qualified JUnit composite dispatch");
    if (dispatch.engineDescriptor().isEmpty()) {
      if (!originalMain(frames)) throw new SecurityException("Missing original JUnit plan thread");
      return;
    }
    int engine = find(frames, compositeEvent + 1,
        type("org.junit.platform.launcher", "org.junit.platform.launcher.core.ExecutionListenerAdapter"),
        event, dispatch.engineDescriptor());
    if (engine < compositeEvent)
      throw new SecurityException("Missing qualified JUnit engine dispatch");
    if (reporting) {
      int context = find(frames, engine + 1,
          type("org.junit.jupiter.engine", "org.junit.jupiter.engine.descriptor.AbstractExtensionContext"),
          "publishReportEntry", "(Ljava/util/Map;)V");
      boolean trusted = false;
      for (int i = Math.max(0, context + 1); i < frames.size(); i++)
        if (reportingCallers.contains(frames.get(i).getDeclaringClass())) trusted = true;
      if (context < engine || !trusted)
        throw new SecurityException("Missing qualified JUnit reporting origin");
      if (!originalMain(frames) && !platformWorker(frames, context + 1) && !apiWorker(frames, context + 1))
        throw new SecurityException("Missing qualified JUnit reporting worker");
    } else if (!originalMain(frames) && !platformWorker(frames, engine + 1))
      throw new SecurityException("Missing qualified JUnit execution worker");
  }
  public static void callback(String event, Set<Class<?>> reportingCallers) {
    callback(frames(), event, reportingCallers);
  }
  public static void lifecycle() {
    List<StackWalker.StackFrame> frames = frames();
    for (StackWalker.StackFrame call : frames) {
      Dispatch event = EVENTS.get(call.getMethodName());
      if (call.getDeclaringClass() == adapter && event != null
          && !call.getMethodName().equals("reportingEntryPublished")
          && call.getDescriptor().equals(event.descriptor())) {
        callback(frames, call.getMethodName(), Set.of());
        return;
      }
    }
    throw new SecurityException("Missing qualified JUnit lifecycle callback");
  }
  public static void scope() {
    List<StackWalker.StackFrame> frames = frames();
    allowedFrames(frames, true, Set.of());
    int invocation = find(frames, 0, type("org.junit.jupiter.engine",
        "org.junit.jupiter.engine.execution.InvocationInterceptorChain$InterceptedInvocation"),
        "proceed", "()Ljava/lang/Object;");
    int node = find(frames, invocation + 1, type("org.junit.platform.engine",
        "org.junit.platform.engine.support.hierarchical.NodeTestTask"), "execute", "()V");
    if (invocation < 0 || !(node > invocation && (originalMain(frames) || platformWorker(frames, invocation + 1))
                           || apiWorker(frames, invocation + 1)))
      throw new SecurityException("Missing qualified JUnit invocation scope");
  }
  public static Class<?> adapter() {
    if (modules.isEmpty()) throw new SecurityException("Runtime registry not bound");
    return adapter;
  }
  public static Class<?> type(String module, String name) {
    Class<?> type = types.get(name);
    if (type == null || type.getModule() != modules.get(module))
      throw new SecurityException("Unknown pinned runtime class");
    return type;
  }
}
