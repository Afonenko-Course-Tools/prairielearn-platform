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
  private static final Map<String, List<Map<String, String>>> CHECKS = new HashMap<>();
  private static final ThreadLocal<String> LEAF = new ThreadLocal<>();
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
  public static synchronized void bind() {
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
      adapter = c;
      bound = true;
      control("main");
    } catch (RuntimeException e) {
      throw e;
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
  public static synchronized void register(String id) {
    control("register");
    if (!REGISTERED.add(id))
      throw new SecurityException("Duplicate register");
  }
  public static synchronized void start(String id) {
    control("executionStarted");
    if (!REGISTERED.contains(id) || !STARTED.add(id))
      throw new SecurityException("Invalid start");
    CHECKS.put(id, new ArrayList<>());
  }
  public static synchronized List<Map<String, String>> finish(String id) {
    control("executionFinished");
    if (!STARTED.remove(id))
      throw new SecurityException("Invalid finish");
    return CHECKS.get(id).stream().map(Map::copyOf).toList();
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
  public static synchronized void open(String id) {
    engine();
    if (LEAF.get() != null || !STARTED.contains(id))
      throw new SecurityException("Invalid leaf scope");
    LEAF.set(id);
  }
  public static void close() {
    engine();
    LEAF.remove();
  }
  public static Map<String, String> begin(
      String property, Object expected, Object actual, Object delta) {
    String leaf = LEAF.get();
    if (!bound || leaf == null)
      return null;
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
      if (c == Scope.class) {
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
    Map<String, String> check = new LinkedHashMap<>();
    synchronized (State.class) {
      if (!STARTED.contains(leaf))
        return null;
      var records = CHECKS.get(leaf);
      if (records.size() >= 64) {
        records.get(63).put("availability", "incomplete: check quota");
        return null;
      }
      check.put("site", site.split("\\|")[0]);
      check.put("property", property);
      check.put("availability", "complete");
      records.add(check);
    }
    check.put("_thread", Long.toString(Thread.currentThread().threadId()));
    check.put("_bci", Integer.toString(caller.getByteCodeIndex()));
    Budget budget = new Budget(Integer.parseInt(POLICY.getProperty("snapshotBytes", "32768")));
    Object e = snapshot(expected, budget, 0), a = snapshot(actual, budget, 0);
    check.put("expected", render(e, budget));
    check.put("actual", render(a, budget));
    check.put("_snapshotArrayPayloadBytes", Integer.toString(budget.allocated));
    check.put("_snapshotArrays", Integer.toString(budget.arrays));
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
    int diff =
        (property.startsWith("равенство") && expected instanceof String && actual instanceof String
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
    return check;
  }
  public static void end(Map<String, String> check, String outcome) {
    if (check != null)
      check.put("delegated", outcome);
  }
  public static void callback(Map<String, String> check, Object actual) {
    if (check != null) {
      Budget b = new Budget(4096);
      check.put("actual", render(snapshot(actual, b, 0), b));
      if (b.incomplete)
        check.put("availability", "incomplete: callback value");
    }
  }
  private static final class Budget {
    int bytes, allocated, arrays, items = 256;
    boolean incomplete;
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
      return "null";
    Class<?> c = value.getClass();
    if (depth > 6) {
      b.incomplete = true;
      return "<depth>";
    }
    if (c == String.class) {
      String s = (String) value;
      if (!b.take(s.length() * 2))
        return "<quota>";
      return s;
    }
    if (c == Boolean.class || c == Character.class || c == Byte.class || c == Short.class
        || c == Integer.class || c == Long.class || c == Float.class || c == Double.class)
      return String.valueOf(value);
    if (c == Class.class)
      return ((Class<?>) value).getName();
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
      Object[] copy = new Object[n];
      b.allocated += n * 4;
      b.arrays++;
      for (int i = 0; i < n; i++) copy[i] = snapshot(values.get(i), b, depth + 1);
      return copy;
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
      if (item != null && item.getClass().isArray())
        append(item, text, owner);
      else if (value instanceof byte[])
        add(String.format("%02x", ((Byte) item) & 255), text, owner);
      else
        add(String.valueOf(item), text, owner);
    }
    add(n > 24 ? ", … length=" + n + "]" : "]", text, owner);
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
    if (expected instanceof String a && actual instanceof String b) {
      for (int i = 0; i < Math.min(a.length(), b.length()); i++)
        if (a.charAt(i) != b.charAt(i))
          return i;
      return a.length() == b.length() ? -1 : Math.min(a.length(), b.length());
    }
    return -1;
  }
}
