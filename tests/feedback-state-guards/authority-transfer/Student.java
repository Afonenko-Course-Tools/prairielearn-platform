import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.security.CodeSource;
import java.security.SecureClassLoader;
import java.util.List;
import java.util.ServiceLoader;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.extension.*;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.launcher.*;

/** Студенческий caller не получает полномочия observer от отражения или чужого loader. */
public class Student {
  @FunctionalInterface interface Action { void run() throws Throwable; }
  private static final ConcurrentHashMap<String, AtomicInteger> ATTEMPTS = new ConcurrentHashMap<>();
  private static final AtomicInteger DENIED = new AtomicInteger(), FOREIGN = new AtomicInteger(),
      FAKE = new AtomicInteger(), STRUCTURAL = new AtomicInteger(), AUDITS = new AtomicInteger();

  static void demand(boolean ok) { if (!ok) throw new IllegalStateException("контроль полномочий"); }
  private static void reached(String label) {
    ATTEMPTS.computeIfAbsent(label, key -> new AtomicInteger()).incrementAndGet();
  }
  private static void denied(String label, Action body) throws Throwable {
    reached(label);
    try {
      body.run();
    } catch (InvocationTargetException wrapper) {
      if (wrapper.getCause() instanceof SecurityException) { DENIED.incrementAndGet(); return; }
      throw wrapper;
    } catch (SecurityException expected) {
      DENIED.incrementAndGet(); return;
    }
    throw new IllegalStateException("Чужой вызов допущен: " + label);
  }

  public static void audit(String context, String uid, String pendingUid, Object record) throws Throwable {
    AUDITS.incrementAndGet();
    Class<?> gate = Class.forName("org.prairielearn.feedback.Gate");
    for (String name : List.of("bind", "register", "start", "finish")) {
      Class<?>[] parameters = name.equals("bind") ? new Class<?>[0] : new Class<?>[]{String.class};
      Object[] arguments = name.equals("bind") ? new Object[0]
          : new Object[]{name.equals("register") ? "unregistered-" + context
              : name.equals("start") ? pendingUid : uid};
      Method method = gate.getMethod(name, parameters);
      denied(context + "/gate-reflect-" + name, () -> method.invoke(null, arguments));
      var handle = MethodHandles.publicLookup().findStatic(gate, name,
          MethodType.methodType(name.equals("finish") ? List.class : void.class, parameters));
      denied(context + "/gate-handle-" + name, () -> handle.invokeWithArguments(arguments));
    }
    adapter(context);
    scope(context, uid);
    projection(context, record);
    reached(context + "/junit-direct");
    org.junit.jupiter.api.Assertions.assertEquals(999001, 999001);
    Class<?> facade = Class.forName("org.prairielearn.feedback.Assertions");
    reached(context + "/facade-reflect");
    facade.getMethod("assertEquals", int.class, int.class).invoke(null, 999002, 999002);
    reached(context + "/facade-handle");
    MethodHandles.publicLookup().findStatic(facade, "assertEquals",
        MethodType.methodType(void.class, int.class, int.class)).invokeExact(999003, 999003);
    reached(context + "/foreign-direct-facade");
    foreign();
    demand(ATTEMPTS.entrySet().stream().filter(e -> e.getKey().startsWith(context + "/"))
        .mapToInt(e -> e.getValue().get()).sum() == 43);
  }

  private static void adapter(String context) throws Throwable {
    Class<?> owner = Class.forName("org.prairielearn.feedback.PlatformJUnitAdapter");
    TestExecutionListener listener = TestExecutionListener.class.cast(owner.getConstructor().newInstance());
    String[] names = {"testPlanExecutionStarted", "dynamicTestRegistered", "executionStarted",
        "executionSkipped", "executionFinished", "testPlanExecutionFinished"};
    Class<?>[][] parameters = {{TestPlan.class}, {TestIdentifier.class}, {TestIdentifier.class},
        {TestIdentifier.class, String.class}, {TestIdentifier.class, TestExecutionResult.class},
        {TestPlan.class}};
    for (int index = 0; index < names.length; index++) {
      final int which = index;
      denied(context + "/adapter-direct-" + names[index], () -> {
        switch (which) {
          case 0 -> listener.testPlanExecutionStarted(null);
          case 1 -> listener.dynamicTestRegistered(null);
          case 2 -> listener.executionStarted(null);
          case 3 -> listener.executionSkipped(null, "foreign");
          case 4 -> listener.executionFinished(null, null);
          case 5 -> listener.testPlanExecutionFinished(null);
          default -> throw new AssertionError("Неизвестный callback");
        }
      });
      Method method = owner.getMethod(names[index], parameters[index]);
      Object[] arguments = new Object[parameters[index].length];
      denied(context + "/adapter-reflect-" + names[index], () -> method.invoke(listener, arguments));
      var handle = MethodHandles.publicLookup().findVirtual(owner, names[index],
          MethodType.methodType(void.class, parameters[index])).bindTo(listener);
      denied(context + "/adapter-handle-" + names[index], () -> handle.invokeWithArguments(arguments));
    }
  }

  private static void scope(String context, String uid) throws Throwable {
    Class<?> scope = Class.forName("org.prairielearn.feedback.internal.Scope");
    InvocationInterceptor provider = InvocationInterceptor.class.cast(
        ServiceLoader.load(Extension.class).stream().filter(p -> p.type() == scope)
            .findFirst().orElseThrow().get());
    ExtensionContext fake = ExtensionContext.class.cast(Proxy.newProxyInstance(
        Student.class.getClassLoader(), new Class<?>[]{ExtensionContext.class},
        (proxy, method, args) -> method.getName().equals("getUniqueId") ? uid : null));
    InvocationInterceptor.Invocation<Void> invocation = () -> { FAKE.incrementAndGet(); return null; };
    AtomicReference<Throwable> failure = new AtomicReference<>();
    // Новый поток не наследует CONTEXT; активный настоящий uid различает именно engine guard.
    Thread outsider = new Thread(() -> {
      try {
        for (String name : List.of("interceptTestMethod", "interceptTestTemplateMethod", "interceptDynamicTest")) {
          boolean dynamic = name.equals("interceptDynamicTest");
          denied(context + "/scope-direct-" + name, () -> {
            if (dynamic) provider.interceptDynamicTest(invocation, null, fake);
            else if (name.equals("interceptTestMethod")) provider.interceptTestMethod(invocation, null, fake);
            else provider.interceptTestTemplateMethod(invocation, null, fake);
          });
          Class<?> middle = dynamic ? DynamicTestInvocationContext.class : ReflectiveInvocationContext.class;
          Class<?>[] parameters = {InvocationInterceptor.Invocation.class, middle, ExtensionContext.class};
          Method method = InvocationInterceptor.class.getMethod(name, parameters);
          denied(context + "/scope-reflect-" + name, () -> method.invoke(provider, invocation, null, fake));
          var handle = MethodHandles.publicLookup().findVirtual(InvocationInterceptor.class, name,
              MethodType.methodType(void.class, parameters)).bindTo(provider);
          denied(context + "/scope-handle-" + name,
              () -> handle.invokeWithArguments(invocation, null, fake));
        }
      } catch (Throwable caught) { failure.set(caught); }
    }, "foreign-scope");
    outsider.start(); outsider.join(3000);
    demand(!outsider.isAlive());
    if (failure.get() != null) throw failure.get();
  }

  private static void projection(String context, Object value) throws Throwable {
    Class<?> projection = Class.forName("org.prairielearn.feedback.ProjectionAccess");
    denied(context + "/projection-require-reflect",
        () -> projection.getMethod("require", Object.class).invoke(null, value));
    var require = MethodHandles.publicLookup().findStatic(projection, "require",
        MethodType.methodType(void.class, Object.class));
    denied(context + "/projection-require-handle", () -> require.invokeWithArguments(value));
    denied(context + "/projection-bridge-reflect",
        () -> projection.getMethod("$pl$c3$component", int.class).invoke(value, 0));
    var bridge = MethodHandles.publicLookup().findVirtual(projection, "$pl$c3$component",
        MethodType.methodType(Object.class, int.class)).bindTo(value);
    denied(context + "/projection-bridge-handle", () -> bridge.invokeWithArguments(0));
  }

  private static void foreign() throws Exception {
    Class<?> real = Class.forName("ForeignHelper");
    byte[] bytes;
    try (var input = real.getResourceAsStream("ForeignHelper.class")) {
      if (input == null) throw new IllegalStateException("Нет compiled helper");
      bytes = input.readAllBytes();
    }
    CodeSource source = real.getProtectionDomain().getCodeSource();
    class Foreign extends SecureClassLoader {
      Class<?> create() { return defineClass("ForeignHelper", bytes, 0, bytes.length, source); }
    }
    Class<?> copy = new Foreign().create();
    demand(copy != real && copy.getProtectionDomain().getCodeSource().equals(source));
    copy.getMethod("check").invoke(null);
  }

  public static void foreignReached() { FOREIGN.incrementAndGet(); }

  public static void structural() throws Exception {
    Class<?> state = Class.forName("org.prairielearn.feedback.internal.State");
    Module module = state.getModule();
    demand(module.isNamed() && !module.isExported("org.prairielearn.feedback.internal")
        && !module.isOpen("org.prairielearn.feedback.internal"));
    STRUCTURAL.incrementAndGet(); demand(!state.getDeclaredField("bound").trySetAccessible());
    STRUCTURAL.incrementAndGet();
    try {
      MethodHandles.privateLookupIn(state, MethodHandles.lookup());
      throw new IllegalStateException("Private lookup открыт");
    } catch (IllegalAccessException expected) {}
    STRUCTURAL.incrementAndGet();
    demand(!Class.forName("org.prairielearn.feedback.internal.Scope").getConstructor().trySetAccessible());
    STRUCTURAL.incrementAndGet();
    try {
      state.getMethod("open", String.class).invoke(null, "foreign");
      throw new IllegalStateException("Internal package экспортирован");
    } catch (IllegalAccessException expected) {}
    Class<?> timeouts = Class.forName("org.prairielearn.feedback.internal.Timeouts");
    for (Method method : timeouts.getDeclaredMethods()) {
      STRUCTURAL.incrementAndGet();
      try {
        method.invoke(null, new Object[method.getParameterCount()]);
        throw new IllegalStateException("Timeout entry экспортирован");
      } catch (IllegalAccessException expected) {}
    }
    for (Class<?> wrapper : timeouts.getDeclaredClasses())
      for (var constructor : wrapper.getDeclaredConstructors()) {
        STRUCTURAL.incrementAndGet(); demand(!constructor.trySetAccessible());
      }
    STRUCTURAL.incrementAndGet();
    try (var input = state.getResourceAsStream("policy.properties")) { demand(input == null); }
    demand(STRUCTURAL.get() == 9);
  }

  public static String summary() {
    int attempts = ATTEMPTS.values().stream().mapToInt(AtomicInteger::get).sum();
    demand(AUDITS.get() == 4 && attempts == 172 && DENIED.get() == 156
        && FOREIGN.get() == 4 && FAKE.get() == 0 && STRUCTURAL.get() == 9);
    demand(ATTEMPTS.values().stream().allMatch(count -> count.get() == 1));
    return "AUTHORITY audits=" + AUDITS.get() + " attempts=" + attempts + " denied=" + DENIED.get()
        + " foreign=" + FOREIGN.get() + " fake=" + FAKE.get() + " structural=" + STRUCTURAL.get();
  }
}
