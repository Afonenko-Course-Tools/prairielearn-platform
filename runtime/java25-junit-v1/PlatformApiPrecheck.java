package org.prairielearn.api;

import java.io.Reader;
import java.lang.reflect.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import javax.tools.*;
import org.json.simple.JSONObject;
import org.json.simple.parser.JSONParser;

/** Узкая граница опубликованного Java API; условия и клиенты задаёт курс. */
public final class PlatformApiPrecheck {
    public static final class Mismatch extends Exception {
        public final String expected, observed;
        Mismatch(String expected, String observed) {
            super("Ожидалось: " + expected + ". Обнаружено: " + observed);
            this.expected = expected; this.observed = observed;
        }
    }

    public static final class Api implements AutoCloseable {
        private final URLClassLoader loader;
        private final Path classes, scratch;
        private int clients;
        Api(Path classes, Path scratch) throws Exception {
            this.classes = classes; this.scratch = scratch;
            loader = new URLClassLoader(new URL[]{classes.toUri().toURL()}, ClassLoader.getPlatformClassLoader());
        }
        /**
         * Имена кандидатов из compiled student directory, без loading/initialization.
         * Для member classes binary name содержит '$'; точный getSimpleName и API
         * проверяет вызывающий после отдельного type(name). Classpath не сканируется.
         */
        public List<String> typeNames(String simpleName) throws java.io.IOException {
            if (simpleName == null || !javax.lang.model.SourceVersion.isIdentifier(simpleName)
                    || javax.lang.model.SourceVersion.isKeyword(simpleName))
                throw new IllegalArgumentException("Нужно простое имя Java-типа");
            if (!Files.isDirectory(classes, LinkOption.NOFOLLOW_LINKS))
                throw new java.io.IOException("Compiled student directory отсутствует или является ссылкой");
            var names = new TreeSet<String>();
            try (var paths = Files.walk(classes)) {
                for (Path path : paths.filter(p -> Files.isRegularFile(p, LinkOption.NOFOLLOW_LINKS)).toList()) {
                    String leaf = path.getFileName().toString();
                    if (!leaf.equals(simpleName + ".class") && !leaf.endsWith("$" + simpleName + ".class")) continue;
                    String binary = classes.relativize(path).toString().replace(java.io.File.separatorChar, '.');
                    names.add(binary.substring(0, binary.length() - ".class".length()));
                }
            }
            return List.copyOf(names);
        }
        public Class<?> type(String name) throws Mismatch {
            try { return Class.forName(name, false, loader); }
            catch (ClassNotFoundException | LinkageError e) { throw new Mismatch("класс " + name, e.toString()); }
        }
        public void expect(boolean condition, String expected, String observed) throws Mismatch {
            if (!condition) throw new Mismatch(expected, observed);
        }
        public Method method(String owner, String name, Class<?> returns, int required, int forbidden, Class<?>... parameters) throws Mismatch {
            String expected = owner + "." + name + Arrays.toString(parameters) + " → " + returns.getTypeName()
                + "; required=" + Modifier.toString(required) + "; forbidden=" + Modifier.toString(forbidden);
            try {
                Class<?> ownerType = type(owner);
                Method m;
                try { m = ownerType.getMethod(name, parameters); }
                catch (NoSuchMethodException notPublic) { m = ownerType.getDeclaredMethod(name, parameters); }
                expect(m.getReturnType().equals(returns) && (m.getModifiers() & required) == required
                    && (m.getModifiers() & forbidden) == 0, expected, m.toGenericString());
                return m;
            } catch (NoSuchMethodException | LinkageError e) { throw new Mismatch(expected, e.toString()); }
        }
        /** Клиенты компилируются независимо; предыдущие клиенты не входят в classpath. */
        public void compiles(String name, String source, boolean expected) throws Exception {
            if (!name.matches("[A-Za-z_$][\\w$]*(\\.[A-Za-z_$][\\w$]*)*")) throw new IllegalArgumentException("Invalid client name");
            Path output = Files.createDirectory(scratch.resolve("client-" + clients++));
            JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
            if (compiler == null) throw new IllegalStateException("JDK compiler missing");
            DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
            JavaFileObject input = new SimpleJavaFileObject(URI.create("string:///" + name.replace('.', '/') + ".java"), JavaFileObject.Kind.SOURCE) {
                @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return source; }
            };
            try (StandardJavaFileManager files = compiler.getStandardFileManager(diagnostics, Locale.ROOT, java.nio.charset.StandardCharsets.UTF_8)) {
                boolean actual = compiler.getTask(null, files, diagnostics,
                    List.of("--release", "25", "-encoding", "UTF-8", "-proc:none", "-Xmaxerrs", "5", "-sourcepath", "", "-classpath", classes.toString(), "-d", output.toString()), null, List.of(input)).call();
                String observed = actual ? "компиляция успешна" : diagnostics.getDiagnostics().stream()
                    .filter(d -> d.getKind() == Diagnostic.Kind.ERROR).map(d -> d.getMessage(Locale.ROOT)).limit(5).reduce((a,b) -> a + "\n" + b).orElse("ошибка компиляции");
                expect(actual == expected, "клиент " + name + (expected ? " компилируется" : " отклоняется компилятором"), observed);
            }
        }
        @Override public void close() throws Exception { loader.close(); }
    }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        Path parameters = Path.of(args[0]);
        JSONObject cfg;
        try (Reader reader = Files.newBufferedReader(parameters)) { cfg = (JSONObject)new JSONParser().parse(reader); }
        Files.delete(parameters);
        JSONObject result = new JSONObject(); result.put("signature", cfg.get("signature"));
        try (Api api = new Api(Path.of((String)cfg.get("classes")), Path.of((String)cfg.get("scratch")))) {
            Method entry = Class.forName((String)cfg.get("entry")).getMethod("check", Api.class);
            if (!Modifier.isStatic(entry.getModifiers()) || entry.getReturnType() != void.class) throw new IllegalStateException("Precheck requires public static void check(Api)");
            try { entry.invoke(null, api); }
            catch (InvocationTargetException e) { throw e.getCause(); }
            result.put("status", "success");
        } catch (Mismatch e) {
            result.put("status", "mismatch"); result.put("expected", e.expected); result.put("observed", e.observed); result.put("message", e.getMessage());
        } catch (Throwable e) {
            result.put("status", "infrastructure"); result.put("message", e.toString());
        }
        Files.writeString(Path.of((String)cfg.get("result_file")), result.toJSONString());
    }
}
