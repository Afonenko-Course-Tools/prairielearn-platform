package org.prairielearn.feedback.internal;
import java.io.*;
import java.lang.reflect.Array;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.stream.*;

/** Закрытый bounded F0 observer; policy не доступен как public mutable state. */
public final class State {
  private static final StackWalker WALK =
      StackWalker.getInstance(Set.of(StackWalker.Option.RETAIN_CLASS_REFERENCE,
          StackWalker.Option.SHOW_HIDDEN_FRAMES, StackWalker.Option.SHOW_REFLECT_FRAMES));
  private static final Properties POLICY = new Properties();
  private static final Module JUNIT = org.junit.jupiter.api.Assertions.class.getModule();
  private static final Map<Class<?>, String> TRUSTED = new IdentityHashMap<>();
  private static final Set<String> REGISTERED = new HashSet<>(), STARTED = new HashSet<>();
  private static final Map<String, Leaf> LEAVES = new HashMap<>();
  private static final ThreadLocal<Context> CONTEXT = new ThreadLocal<>();
  private static final ThreadLocal<Check> READING = new ThreadLocal<>();
  private static final Map<Class<?>, Projection> PROJECTIONS = new IdentityHashMap<>();
  private record Projection(String[] names) {}
  private static long epoch;
  private static final Object LOCK = new Object();
  private static final class Leaf {
    final String id;
    final long epoch;
    boolean live = true;
    final List<Check> checks = new ArrayList<>();
    final List<Grant> grants = new ArrayList<>();
    Leaf(String id) {
      this.id = id;
      this.epoch = ++State.epoch;
    }
  }
  record Context(Leaf leaf, Grant grant) {}
  public static final class Check {
    private final Context context;
    private Map<String, String> values;
    private final String site, property, thread, bci;
    private boolean ready;
    private Check(Context context, String site, String property, int bci) {
      this.context = context;
      this.site = site;
      this.property = property;
      this.thread = Long.toString(Thread.currentThread().threadId());
      this.bci = Integer.toString(bci);
    }
  }
  public static final class Grant {
    private final Context parent;
    private final int depth;
    private final Check observation;
    private int state; // CREATED=0, ACTIVE=1, CLOSED=2, REVOKED=3
    private Thread worker;
    private Grant(Check check) {
      this.parent = check.context;
      observation = check;
      depth = parent.grant == null ? 1 : parent.grant.depth + 1;
    }
  }
  private static boolean live(Context context) {
    if (context == null || !context.leaf.live || !STARTED.contains(context.leaf.id))
      return false;
    for (Grant g = context.grant; g != null; g = g.parent.grant)
      if (g.state != 1)
        return false;
    return context.grant == null || context.grant.worker == Thread.currentThread();
  }
  private static void moduleCaller(Class<?> expected) {
    var frames = stack();
    int i = 0;
    while (i < frames.size() && frames.get(i).getDeclaringClass() == State.class) i++;
    if (i == frames.size() || frames.get(i).getDeclaringClass() != expected)
      throw new SecurityException("Wrong internal entry caller");
  }
  private static final Set<Class<?>> LISTS = Set.copyOf(
      Arrays.asList(List.of().getClass(), List.of(1).getClass(), Stream.of(1).toList().getClass()));
  private static Class<?> adapter;
  private static final Set<Class<?>> ADAPTER = Collections.newSetFromMap(new IdentityHashMap<>());
  private static boolean bound;
  static {
    try (var in = State.class.getResourceAsStream("policy.properties")) {
      if (in == null)
        throw new IOException("Missing private manifest");
      POLICY.load(in);
    } catch (Exception e) {
      throw new ExceptionInInitializerError(e);
    }
  }
  private static List<StackWalker.StackFrame> stack() {
    return WALK.walk(s -> s.toList());
  }
  private static Path origin(Class<?> c) throws Exception {
    return Path.of(c.getProtectionDomain().getCodeSource().getLocation().toURI()).toRealPath();
  }
  private static String hash(Path p) throws Exception {
    return HexFormat.of().formatHex(
        MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(p)));
  }
  private static int outside(List<StackWalker.StackFrame> frames) {
    int i = 0;
    while (i < frames.size()
        && frames.get(i).getDeclaringClass().getModule() == State.class.getModule())
      i++;
    return i;
  }
  private static boolean runtime(Class<?> c) {
    return c.getModule() == JUNIT || c.getClassLoader() == null;
  }
  private static void control(String method) {
    if (!bound)
      throw new SecurityException("Observer not bound");
    var frames = stack();
    int i = outside(frames);
    if (i == frames.size())
      throw new SecurityException("Missing caller");
    var caller = frames.get(i);
    String site = "controlsite." + caller.getDeclaringClass().getName() + "|"
        + caller.getMethodName() + "|" + caller.getDescriptor() + "|" + caller.getByteCodeIndex();
    if (caller.getDeclaringClass() != adapter || !caller.getMethodName().equals(method)
        || !POLICY.containsKey(site))
      throw new SecurityException("Wrong lifecycle site");
    boolean engine = method.equals("main");
    for (int j = i + 1; j < frames.size(); j++) {
      Class<?> c = frames.get(j).getDeclaringClass();
      if (c == adapter && frames.get(j).getMethodName().equals("main"))
        break;
      if (c.getModule() == JUNIT)
        engine = true;
      else if (!runtime(c) && !ADAPTER.contains(c))
        throw new SecurityException("Untrusted lifecycle intermediary");
    }
    if (!engine)
      throw new SecurityException("Missing engine caller");
  }
  public static void bind() {
    synchronized (LOCK) {
      try {
        if (bound)
          throw new SecurityException("Repeated bind");
        var frames = stack();
        var caller = frames.get(outside(frames));
        Class<?> c = caller.getDeclaringClass();
        Path root = Path.of(POLICY.getProperty("adapterRoot")).toRealPath();
        if (!c.getName().equals("PlatformJUnitAdapter")
            || c.getClassLoader() != ClassLoader.getSystemClassLoader() || !origin(c).equals(root)
            || !hash(root.resolve("PlatformJUnitAdapter.class"))
                .equals(POLICY.getProperty("adapterClass.PlatformJUnitAdapter")))
          throw new SecurityException("Wrong bootstrap identity");
        if (!JUNIT.isNamed() || !JUNIT.getName().equals("org.junit.platform.console.standalone")
            || !hash(origin(org.junit.jupiter.api.Assertions.class))
                .equals(POLICY.getProperty("junitHash")))
          throw new SecurityException("Wrong JUnit identity");
        Path tests = Path.of(POLICY.getProperty("trustedRoot")).toRealPath();
        for (String key : POLICY.stringPropertyNames())
          if (key.startsWith("class.")) {
            String name = key.substring(6);
            Class<?> type = Class.forName(name, false, c.getClassLoader());
            if (type.getClassLoader() != c.getClassLoader() || !origin(type).equals(tests)
                || !hash(tests.resolve(name.replace('.', '/') + ".class"))
                    .equals(POLICY.getProperty(key)))
              throw new SecurityException("Stale trusted class");
            TRUSTED.put(type, name);
          }
        for (String key : POLICY.stringPropertyNames())
          if (key.startsWith("adapterClass.")) {
            String name = key.substring(13);
            Class<?> type = Class.forName(name, false, c.getClassLoader());
            if (type.getClassLoader() != c.getClassLoader() || !origin(type).equals(root)
                || !hash(root.resolve(name.replace('.', '/') + ".class"))
                    .equals(POLICY.getProperty(key)))
              throw new SecurityException("Stale adapter class");
            ADAPTER.add(type);
          }
        for (String key : POLICY.stringPropertyNames())
          if (key.startsWith("projection.")) {
            String name = key.substring(11);
            Class<?> type = Class.forName(name, false, c.getClassLoader());
            String[] schema = POLICY.getProperty(key).split("\\|");
            if (!TRUSTED.containsKey(type) || !type.isRecord() || schema.length == 0
                || schema.length > 16
                || !org.prairielearn.feedback.ProjectionAccess.class.isAssignableFrom(type)
                || !"1".equals(POLICY.getProperty("projectionGuard." + name)))
              throw new SecurityException("Invalid projection admission");
            var components = type.getRecordComponents();
            if (components.length != schema.length)
              throw new SecurityException("Stale projection schema");
            for (int j = 0; j < schema.length; j++) {
              if (components[j].getName().length() > 128
                  || !schema[j].equals(
                      components[j].getName() + ":" + components[j].getType().descriptorString()))
                throw new SecurityException("Stale projection schema");
            }
            String[] names = new String[components.length];
            for (int j = 0; j < names.length; j++) names[j] = components[j].getName();
            PROJECTIONS.put(type, new Projection(names));
          }
        adapter = c;
        bound = true;
        control("main");
      } catch (RuntimeException e) {
        throw e;
      } catch (Exception e) {
        throw new IllegalStateException(e);
      }
    }
  }
  public static void register(String id) {
    synchronized (LOCK) {
      control("register");
      if (!REGISTERED.add(id))
        throw new SecurityException("Duplicate register");
    }
  }
  public static void start(String id) {
    synchronized (LOCK) {
      control("executionStarted");
      if (!REGISTERED.contains(id) || !STARTED.add(id))
        throw new SecurityException("Invalid start");
      LEAVES.put(id, new Leaf(id));
    }
  }
  public static List<Map<String, String>> finish(String id) {
    synchronized (LOCK) {
      control("executionFinished");
      if (!STARTED.remove(id))
        throw new SecurityException("Invalid finish");
      Leaf leaf = LEAVES.get(id);
      revokeLeaf(leaf);
      List<Map<String, String>> result = new ArrayList<>();
      for (Check check : leaf.checks) {
        Map<String, String> value = new LinkedHashMap<>();
        value.put("site", check.site);
        value.put("property", check.property);
        value.put("_thread", check.thread);
        value.put("_bci", check.bci);
        value.put("expected", "<unavailable>");
        value.put("actual", "<unavailable>");
        value.put("delegated", "unknown");
        value.put("availability", "incomplete: pending observation");
        if (check.ready)
          value.putAll(check.values);
        if (!check.ready || !value.containsKey("delegated")
            || value.get("delegated").equals("unknown"))
          value.put("availability", "incomplete: pending observation");
        result.add(Map.copyOf(value));
      }
      return List.copyOf(result);
    }
  }
  private static void engine() {
    var frames = stack();
    int i = outside(frames);
    boolean anchor = false;
    for (; i < frames.size(); i++) {
      Class<?> c = frames.get(i).getDeclaringClass();
      if (c.getModule() == JUNIT)
        anchor = true;
      else if (!runtime(c) && !ADAPTER.contains(c))
        throw new SecurityException("Untrusted scope caller");
    }
    if (!anchor)
      throw new SecurityException("Missing engine scope caller");
  }
  public static void open(String id) {
    synchronized (LOCK) {
      engine();
      if (CONTEXT.get() != null || !STARTED.contains(id))
        throw new SecurityException("Invalid leaf scope");
      CONTEXT.set(new Context(LEAVES.get(id), null));
    }
  }
  private static void revokeLeaf(Leaf leaf) {
    leaf.live = false;
    for (Grant g : leaf.grants) g.state = 3;
  }
  public static void close() {
    synchronized (LOCK) {
      engine();
      Context context = CONTEXT.get();
      if (context != null)
        revokeLeaf(context.leaf);
      CONTEXT.remove();
    }
  }
  public static Check begin(String property, Object expected, Object actual, Object delta) {
    Context context = CONTEXT.get();
    synchronized (LOCK) {
      if (!bound || !live(context))
        return null;
    }
    var frames = stack();
    int i = outside(frames);
    if (i == frames.size())
      return null;
    var caller = frames.get(i);
    String owner = TRUSTED.get(caller.getDeclaringClass());
    if (owner == null)
      return null;
    String site = POLICY.getProperty("site." + owner + "|" + caller.getMethodName() + "|"
        + caller.getDescriptor() + "|" + caller.getByteCodeIndex());
    if (site == null)
      return null;
    boolean anchor = false;
    for (int j = i + 1; j < frames.size(); j++) {
      Class<?> c = frames.get(j).getDeclaringClass();
      if (context.grant == null && c == Scope.class
          || context.grant != null
              && (c == Timeouts.ExecutableWrapper.class || c == Timeouts.SupplierWrapper.class)) {
        anchor = true;
        break;
      }
      if (TRUSTED.containsKey(c) || runtime(c))
        continue;
      var previous = frames.get(j - 1);
      if (c.isHidden() && c.getClassLoader() == caller.getDeclaringClass().getClassLoader()
          && c.getNestHost() == previous.getDeclaringClass()
          && TRUSTED.containsKey(previous.getDeclaringClass())
          && previous.getMethodName().startsWith("lambda$"))
        continue;
      return null;
    }
    if (!anchor)
      return null;
    Check handle;
    synchronized (LOCK) {
      if (!live(context))
        return null;
      var records = context.leaf.checks;
      if (records.size() >= 64) {
        Check last = records.get(63);
        if (last.ready)
          last.values.put("availability", "incomplete: check quota");
        return null;
      }
      handle = new Check(context, site.split("\\|")[0], property, caller.getByteCodeIndex());
      records.add(handle);
    }
    Map<String, String> check = new LinkedHashMap<>();
    check.put("availability", "complete");
    READING.set(handle);
    try {
      Budget budget = new Budget(Integer.parseInt(POLICY.getProperty("snapshotBytes", "32768")));
      Object e = snapshot(expected, budget, 0), a = snapshot(actual, budget, 0);
      check.put("expected", render(e, budget));
      check.put("actual", render(a, budget));
      check.put("_snapshotArrayPayloadBytes", Integer.toString(budget.allocated));
      check.put("_snapshotArrays", Integer.toString(budget.arrays));
      check.put("_snapshotRecordNodes", Integer.toString(budget.recordNodes));
      check.put("_snapshotRecordComponents", Integer.toString(budget.recordComponents));
      if (delta != null)
        check.put("delta", render(snapshot(delta, budget, 0), budget));
      if (budget.incomplete)
        check.put("availability", "incomplete: snapshot quota or unsupported type");
      if (property.equals("совпадение ссылок") || property.equals("различие ссылок")) {
        check.put(
            "expected", property.equals("совпадение ссылок") ? "та же ссылка" : "разные ссылки");
        check.put("actual", expected == actual ? "та же ссылка" : "разные ссылки");
        check.put("availability", "complete");
      }
      if (property.equals("null") || property.equals("не null")) {
        check.put("expected", property);
        check.put("actual", actual == null ? "null" : "не null");
        check.put("availability", "complete");
      }
      int diff = (property.startsWith("равенство") && expected instanceof String
                         && actual instanceof String
                     || expected != null && actual != null && expected.getClass().isArray()
                         && actual.getClass().isArray())
          ? firstDifference(e, a, delta)
          : -1;
      if (diff >= 0) {
        check.put("differenceIndex", Integer.toString(diff));
        if (e instanceof byte[] left && a instanceof byte[] right
            && diff < Math.min(left.length, right.length)) {
          check.put("differenceExpected", String.format("%02x", left[diff] & 255));
          check.put("differenceActual", String.format("%02x", right[diff] & 255));
        }
      }
      synchronized (LOCK) {
        if (live(context)) {
          handle.values = check;
          handle.ready = true;
        }
      }
    } catch (RuntimeException failure) {
      synchronized (LOCK) {
        if (live(context)) {
          check.put("expected", "<unavailable>");
          check.put("actual", "<unavailable>");
          check.put("availability", "incomplete: observation failed");
          handle.values = check;
          handle.ready = true;
        }
      }
    } finally {
      READING.remove();
    }
    return handle;
  }
  public static void end(Check check, String outcome) {
    moduleCaller(org.prairielearn.feedback.Assertions.class);
    if (check == null)
      return;
    synchronized (LOCK) {
      if (check.ready && live(check.context)) {
        check.values.put("delegated", outcome);
        if (check.property.equals("preemptive timeout")
            && check.values.get("actual").equals("<unavailable>"))
          check.values.put("availability", "incomplete: callback has no returned value");
      }
    }
  }
  public static void callback(Check check, Object actual) {
    moduleCaller(org.prairielearn.feedback.Assertions.class);
    if (check == null)
      return;
    synchronized (LOCK) {
      if (!live(check.context))
        return;
    }
    Budget budget = new Budget(4096);
    String value;
    READING.set(check);
    try {
      value = render(snapshot(actual, budget, 0), budget);
    } catch (RuntimeException failure) {
      value = "<unavailable>";
      budget.incomplete = true;
    } finally {
      READING.remove();
    }
    synchronized (LOCK) {
      if (check.ready && live(check.context)) {
        check.values.put("actual", value);
        if (budget.incomplete)
          check.values.put("availability", "incomplete: callback value");
      }
    }
  }
  public static Grant grant(Check check) {
    moduleCaller(org.prairielearn.feedback.Assertions.class);
    synchronized (LOCK) {
      if (check == null || !check.ready || !live(check.context))
        return null;
      Grant grant = new Grant(check);
      if (grant.depth > 4) {
        check.values.put("availability", "incomplete: timeout depth");
        return null;
      }
      check.context.leaf.grants.add(grant);
      return grant;
    }
  }
  public static void revoke(Grant grant) {
    moduleCaller(org.prairielearn.feedback.Assertions.class);
    synchronized (LOCK) {
      if (grant != null)
        grant.state = 3;
    }
  }
  private static boolean worker(boolean executable) {
    var frames = stack();
    int i = outside(frames);
    Class<?> boundary;
    try {
      boundary = Class.forName("org.junit.jupiter.api.AssertTimeoutPreemptively", false,
          org.junit.jupiter.api.Assertions.class.getClassLoader());
    } catch (ClassNotFoundException e) {
      return false;
    }
    // Hidden JUnit adapters are pinned to this exact class/module, not any JUnit frame.
    if (executable) {
      if (i >= frames.size())
        return false;
      var call = frames.get(i++);
      if (call.getDeclaringClass() != boundary
          || !(call.getMethodName().equals("lambda$assertTimeoutPreemptively$0")
              || call.getMethodName().equals("lambda$assertTimeoutPreemptively$1"))
          || !call.getDescriptor().equals(
              "(Lorg/junit/jupiter/api/function/Executable;)Ljava/lang/Object;")
          || call.getByteCodeIndex() != 1)
        return false;
      if (i < frames.size() && frames.get(i).getDeclaringClass().isHidden()
          && frames.get(i).getDeclaringClass().getNestHost() == boundary)
        i++;
    }
    if (i >= frames.size())
      return false;
    var call = frames.get(i);
    return call.getDeclaringClass() == boundary
        && call.getMethodName().equals("lambda$submitTask$3")
        && call.getDescriptor().equals(
            "(Ljava/util/concurrent/atomic/AtomicReference;Lorg/junit/jupiter/api/function/ThrowingSupplier;)Ljava/lang/Object;")
        && call.getByteCodeIndex() == 8;
  }
  record Activation(Context previous, Context installed) {}
  static Activation activate(Grant grant, boolean executable) {
    moduleCaller(executable ? Timeouts.ExecutableWrapper.class : Timeouts.SupplierWrapper.class);
    boolean qualified = worker(executable);
    synchronized (LOCK) {
      Context previous = CONTEXT.get();
      if (grant == null || grant.state != 0 || !qualified || !liveAncestor(grant.parent)) {
        CONTEXT.remove();
        if (grant != null && grant.observation.ready && liveAncestor(grant.parent))
          grant.observation.values.put("availability", "incomplete: worker grant rejected");
        return new Activation(previous, null);
      }
      grant.state = 1;
      grant.worker = Thread.currentThread();
      Context installed = new Context(grant.parent.leaf, grant);
      CONTEXT.set(installed);
      return new Activation(previous, installed);
    }
  }
  private static boolean liveAncestor(Context context) {
    if (context == null || !context.leaf.live || !STARTED.contains(context.leaf.id))
      return false;
    for (Grant g = context.grant; g != null; g = g.parent.grant)
      if (g.state != 1)
        return false;
    return true;
  }
  static void deactivate(Grant grant, Activation activation, boolean executable) {
    moduleCaller(executable ? Timeouts.ExecutableWrapper.class : Timeouts.SupplierWrapper.class);
    synchronized (LOCK) {
      if (activation.installed != null && grant != null && grant.worker == Thread.currentThread()
          && grant.state == 1)
        grant.state = 2;
      if (activation.previous == null)
        CONTEXT.remove();
      else
        CONTEXT.set(activation.previous);
    }
  }
  public static void requireProjection(Object value) {
    var frames = stack();
    int i = outside(frames);
    if (i + 1 >= frames.size())
      throw new SecurityException("Missing projection anchor");
    var bridge = frames.get(i);
    var reader = frames.get(i + 1);
    Check check = READING.get();
    synchronized (LOCK) {
      if (check == null || !live(check.context) || value == null
          || !PROJECTIONS.containsKey(value.getClass())
          || bridge.getDeclaringClass() != value.getClass()
          || !bridge.getMethodName().equals("$pl$c3$component")
          || !bridge.getDescriptor().equals("(I)Ljava/lang/Object;")
          || bridge.getByteCodeIndex() != 1 || reader.getDeclaringClass() != State.class
          || !reader.getMethodName().equals("readComponent")
          || !reader.getDescriptor().equals("(Ljava/lang/Object;I)Ljava/lang/Object;")
          || reader.getByteCodeIndex() != Integer.parseInt(POLICY.getProperty("readerBci", "-1")))
        throw new SecurityException("Wrong projection reader");
    }
  }
  private static Object readComponent(Object value, int ordinal) {
    // Class identity is checked before dispatch: a fake implementation is never invoked.
    if (!PROJECTIONS.containsKey(value.getClass()))
      throw new SecurityException("Unadmitted projection");
    return ((org.prairielearn.feedback.ProjectionAccess) value).$pl$c3$component(ordinal);
  }
  private record Text(String value) {}
  private enum NullValue { INSTANCE }
  private record RecordNode(String[] names, Object[] values) {}
  private static final class Budget {
    int bytes, allocated, arrays, recordNodes, recordComponents, items = 256;
    boolean incomplete;
    final IdentityHashMap<Object, Boolean> ancestors = new IdentityHashMap<>();
    Budget(int bytes) {
      this.bytes = bytes;
    }
    boolean take(int n) {
      if (n < 0 || n > bytes) {
        incomplete = true;
        return false;
      }
      bytes -= n;
      return true;
    }
  }
  private static Object snapshot(Object value, Budget b, int depth) {
    if (depth > 6 || b.items-- <= 0) {
      b.incomplete = true;
      return "<depth/item quota>";
    }
    if (value == null)
      return NullValue.INSTANCE;
    Class<?> c = value.getClass();
    if (depth > 6) {
      b.incomplete = true;
      return "<depth>";
    }
    if (c == String.class) {
      String s = (String) value;
      if (!b.take(s.length() * 2))
        return "<quota>";
      return new Text(s);
    }
    if (c == Boolean.class || c == Character.class || c == Byte.class || c == Short.class
        || c == Integer.class || c == Long.class || c == Float.class || c == Double.class)
      return String.valueOf(value);
    if (c == Class.class)
      return ((Class<?>) value).getName();
    Projection projection = PROJECTIONS.get(c);
    if (projection != null) {
      int n = projection.names.length;
      // Reserve node, names/value references, and worst-case primitive boxing before
      // dispatch/allocation.
      if (n > b.items || !b.take(16 + n * 56)) {
        b.incomplete = true;
        return "<record quota before allocation>";
      }
      if (b.ancestors.put(value, Boolean.TRUE) != null) {
        b.incomplete = true;
        return "<cycle>";
      }
      b.items -= n;
      Object[] values = new Object[n];
      try {
        for (int i = 0; i < n; i++) {
          b.recordComponents++;
          values[i] = snapshot(readComponent(value, i), b, depth + 1);
        }
      } finally {
        b.ancestors.remove(value);
      }
      b.recordNodes++;
      return new RecordNode(projection.names, values);
    }
    if (c.isArray()) {
      int n = Array.getLength(value);
      Class<?> component = c.getComponentType();
      int width = component == byte.class || component == boolean.class ? 1
          : component == short.class || component == char.class         ? 2
          : component == long.class || component == double.class        ? 8
                                                                        : 4;
      if (n > 32768) {
        b.incomplete = true;
        return "<quota before array allocation>";
      }
      if (!b.take(n * width))
        return "<quota before array allocation>";
      if (b.ancestors.put(value, Boolean.TRUE) != null) {
        b.incomplete = true;
        return "<cycle>";
      }
      try {
        if (component.isPrimitive()) {
          Object copy = Array.newInstance(component, n);
          b.allocated += n * width;
          b.arrays++;
          System.arraycopy(value, 0, copy, 0, n);
          return copy;
        }
        if (n > b.items) {
          b.incomplete = true;
          return "<item quota>";
        }
        Object[] copy = new Object[n];
        b.allocated += n * 4;
        b.arrays++;
        for (int i = 0; i < n; i++) copy[i] = snapshot(Array.get(value, i), b, depth + 1);
        return copy;
      } finally {
        b.ancestors.remove(value);
      }
    }
    if (LISTS.contains(c) && c.getClassLoader() == null) {
      List<?> values = (List<?>) value;
      int n = values.size();
      if (n > b.items) {
        b.incomplete = true;
        return "<sequence item quota>";
      }
      if (!b.take(n * 4))
        return "<sequence byte quota>";
      if (b.ancestors.put(value, Boolean.TRUE) != null) {
        b.incomplete = true;
        return "<cycle>";
      }
      try {
        Object[] copy = new Object[n];
        b.allocated += n * 4;
        b.arrays++;
        for (int i = 0; i < n; i++) copy[i] = snapshot(values.get(i), b, depth + 1);
        return copy;
      } finally {
        b.ancestors.remove(value);
      }
    }
    b.incomplete = true;
    return "<opaque:" + c.getName() + ">";
  }
  private static String render(Object value, Budget owner) {
    StringBuilder text = new StringBuilder();
    append(value, text, owner);
    return text.toString();
  }
  private static void add(String value, StringBuilder text, Budget owner) {
    int left = 2048 - text.length();
    if (value.length() > left) {
      owner.incomplete = true;
      if (left > 0)
        text.append(value, 0, left);
    } else
      text.append(value);
  }
  private static void append(Object value, StringBuilder text, Budget owner) {
    if (text.length() >= 2048) {
      owner.incomplete = true;
      return;
    }
    if (value instanceof RecordNode node) {
      add("{", text, owner);
      for (int i = 0; i < node.names.length; i++) {
        if (i > 0)
          add(", ", text, owner);
        add(node.names[i] + "=", text, owner);
        appendNested(node.values[i], text, owner);
      }
      add("}", text, owner);
      return;
    }
    if (value == NullValue.INSTANCE) {
      add("null", text, owner);
      return;
    }
    if (value instanceof Text string) {
      add(string.value, text, owner);
      return;
    }
    if (value instanceof String string) {
      add(string, text, owner);
      return;
    }
    int n = Array.getLength(value);
    add("[", text, owner);
    for (int i = 0; i < Math.min(n, 24); i++) {
      if (i > 0)
        add(", ", text, owner);
      Object item = Array.get(value, i);
      if (value instanceof Object[])
        appendNested(item, text, owner);
      else if (value instanceof byte[])
        add(String.format("%02x", ((Byte) item) & 255), text, owner);
      else
        add(String.valueOf(item), text, owner);
    }
    add(n > 24 ? ", … length=" + n + "]" : "]", text, owner);
  }
  private static void appendNested(Object value, StringBuilder text, Budget owner) {
    if (value instanceof Text string) {
      add("\"", text, owner);
      for (int i = 0; i < string.value.length() && text.length() < 2048; i++) {
        char c = string.value.charAt(i);
        add(switch (c) {
          case '\\' -> "\\\\";
          case '\"' -> "\\\"";
          case '\n' -> "\\n";
          case '\r' -> "\\r";
          case '\t' -> "\\t";
          default -> Character.toString(c);
        }, text, owner);
      }
      add("\"", text, owner);
    } else
      append(value, text, owner);
  }
  private static int firstDifference(Object expected, Object actual, Object delta) {
    if (expected instanceof byte[] a && actual instanceof byte[] b) {
      for (int i = 0; i < Math.min(a.length, b.length); i++)
        if (a[i] != b[i])
          return i;
      return a.length == b.length ? -1 : Math.min(a.length, b.length);
    }
    if (expected instanceof int[] a&& actual instanceof int[] b) {
      for (int i = 0; i < Math.min(a.length, b.length); i++)
        if (a[i] != b[i])
          return i;
      return a.length == b.length ? -1 : Math.min(a.length, b.length);
    }
    if (expected instanceof double[] a&& actual instanceof double[] b) {
      double d = delta instanceof Double x ? x : 0;
      for (int i = 0; i < Math.min(a.length, b.length); i++)
        if (Double.compare(a[i], b[i]) != 0 && !(Math.abs(a[i] - b[i]) <= d))
          return i;
      return a.length == b.length ? -1 : Math.min(a.length, b.length);
    }
    if (expected instanceof Text left && actual instanceof Text right) {
      String a = left.value, b = right.value;
      for (int i = 0; i < Math.min(a.length(), b.length()); i++)
        if (a.charAt(i) != b.charAt(i))
          return i;
      return a.length() == b.length() ? -1 : Math.min(a.length(), b.length());
    }
    return -1;
  }
}
