package org.prairielearn.feedback;

import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClass;

import org.json.simple.*;
import org.json.simple.parser.JSONParser;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.engine.reporting.ReportEntry;
import org.junit.platform.engine.support.descriptor.ClassSource;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.launcher.*;
import org.junit.platform.launcher.core.*;
import org.opentest4j.AssertionFailedError;
import org.prairielearn.autograder.AutograderInfo;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Результаты и диагностика через публичные события JUnit и OpenTest4J. */
public final class PlatformJUnitAdapter implements TestExecutionListener {
    private TestPlan plan;
    private boolean complete;
    private int containerFailures;
    private final Set<String> registered = new LinkedHashSet<>();
    private final Set<String> started = new LinkedHashSet<>();
    private final Map<String, String> outcomes = new LinkedHashMap<>();
    private final Map<String, String> failureKinds = new LinkedHashMap<>();
    private final Map<String, Map<String, Object>> cases = new LinkedHashMap<>();
    private final Map<String, Map<String, Object>> grading = new LinkedHashMap<>();
    private final Map<String, Double> classMaximums = new LinkedHashMap<>();
    private final List<String> studentClasses;
    private final List<Map<String, String>> containerDiagnostics = new ArrayList<>();

    private PlatformJUnitAdapter(List<String> studentClasses) {
        this.studentClasses = studentClasses;
    }

    private static String bounded(String value, int maximum) {
        return value == null ? "" : value.substring(0, Math.min(maximum, value.length()));
    }

    private Map<String, Object> report(TestIdentifier test) {
        return cases.computeIfAbsent(
                test.getUniqueId(),
                id -> {
                    Map<String, Object> value = new LinkedHashMap<>();
                    value.put("id", id);
                    value.put("name", bounded(test.getDisplayName(), 8192));
                    if (test.getSource().orElse(null) instanceof MethodSource method)
                        value.put("test", method.getClassName() + "#" + method.getMethodName());
                    return value;
                });
    }

    private void register(TestIdentifier test) {
        if (!registered.add(test.getUniqueId())) return;
        double weight = 1;
        String name = test.getDisplayName(), description = "";
        for (var tag : test.getTags())
            if (tag.getName().startsWith("points="))
                weight = Double.parseDouble(tag.getName().substring(7));
        if (test.getSource().orElse(null) instanceof MethodSource method) {
            AutograderInfo info =
                    method.getJavaMethod().getDeclaredAnnotation(AutograderInfo.class);
            if (info != null) {
                if (info.points() > 0) weight = info.points();
                if (!info.name().isEmpty()) name = info.name();
                description = info.description();
            }
        }
        if (!Double.isFinite(weight) || weight < 0)
            throw new IllegalArgumentException("Invalid JUnit points");
        TestPlan activePlan = Objects.requireNonNull(plan, "JUnit plan has not started");
        TestIdentifier owner = activePlan.getParent(test).orElse(null);
        while (owner != null && !(owner.getSource().orElse(null) instanceof ClassSource))
            owner = activePlan.getParent(owner).orElse(null);
        grading.put(
                test.getUniqueId(),
                Map.of(
                        "weight",
                        weight,
                        "name",
                        name,
                        "description",
                        description,
                        "owner",
                        owner == null ? "" : owner.getUniqueId()));
    }

    @Override
    public synchronized void testPlanExecutionStarted(TestPlan plan) {
        this.plan = plan;
        for (TestIdentifier root : plan.getRoots()) {
            List<TestIdentifier> nodes = new ArrayList<>();
            nodes.add(root);
            nodes.addAll(plan.getDescendants(root));
            for (TestIdentifier node : nodes) {
                if (node.isTest()) register(node);
                if (node.getSource().orElse(null) instanceof ClassSource)
                    for (var tag : node.getTags())
                        if (tag.getName().startsWith("maxpoints=")) {
                            double maximum = Double.parseDouble(tag.getName().substring(10));
                            if (!Double.isFinite(maximum) || maximum < 0)
                                throw new IllegalArgumentException("Invalid JUnit maxpoints");
                            classMaximums.put(node.getUniqueId(), maximum);
                        }
            }
        }
    }

    @Override
    public synchronized void dynamicTestRegistered(TestIdentifier test) {
        if (test.isTest()) register(test);
    }

    @Override
    public synchronized void executionStarted(TestIdentifier test) {
        if (test.isTest()) started.add(test.getUniqueId());
    }

    @Override
    public synchronized void executionSkipped(TestIdentifier test, String reason) {
        List<TestIdentifier> nodes = new ArrayList<>();
        nodes.add(test);
        TestPlan activePlan = Objects.requireNonNull(plan, "JUnit plan has not started");
        nodes.addAll(activePlan.getDescendants(test));
        for (TestIdentifier child : nodes)
            if (child.isTest()) {
                outcomes.put(child.getUniqueId(), "skipped");
                report(child).put("status", "skipped");
                report(child).put("message", bounded(reason, 8192));
            }
    }

    private boolean studentFrame(StackTraceElement frame) {
        return studentClasses.stream()
                .anyMatch(name ->
                        frame.getClassName().equals(name)
                                || frame.getClassName().startsWith(name + "$"));
    }

    private String failureKind(Throwable failure) {
        String name = failure.getClass().getName();
        if (name.equals("coursesupport.JavaProcess$StudentTimeout")) return "timeout";
        if (name.equals("coursesupport.JavaProcess$StudentOutputLimit")) return "output-limit";
        if (name.equals("coursesupport.JavaProcess$UncaughtStudentException")) return "runtime";
        Throwable cause = failure;
        for (int depth = 0; cause != null && depth < 16; depth++, cause = cause.getCause())
            for (StackTraceElement frame : cause.getStackTrace())
                if (studentFrame(frame)) return "runtime";
        if (failure instanceof AssertionError || failure instanceof ReflectiveOperationException)
            return "wrong-answer";
        return "infrastructure";
    }

    private static Map<String, String> diagnostic(Throwable failure) {
        StringWriter trace = new StringWriter();
        failure.printStackTrace(new PrintWriter(trace));
        StringBuilder message = new StringBuilder(bounded(failure.getMessage(), 8192));
        StringBuilder relevant = new StringBuilder();
        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        Throwable cause = failure;
        for (int depth = 0;
                cause != null && depth < 16 && seen.add(cause);
                depth++, cause = cause.getCause()) {
            if (depth > 0) {
                String label =
                        "Причина: "
                                + cause.getClass().getName()
                                + ": "
                                + bounded(cause.getMessage(), 8192);
                if (message.length() < 8192) {
                    if (!message.isEmpty()) message.append('\n');
                    message.append(label);
                }
                if (relevant.length() < 8192) relevant.append(label).append('\n');
            }
            for (StackTraceElement frame : cause.getStackTrace()) {
                if (relevant.length() >= 8192) break;
                String name = frame.getClassName();
                if (!name.startsWith("org.junit.")
                        && !name.startsWith("org.opentest4j.")
                        && !name.startsWith("java.")
                        && !name.startsWith("jdk.")
                        && !name.equals(PlatformJUnitAdapter.class.getName()))
                    relevant.append("at ").append(frame).append('\n');
            }
        }
        return Map.of(
                "message",
                bounded(message.toString(), 8192),
                "exceptionType",
                failure.getClass().getName(),
                "stackTrace",
                bounded(relevant.toString(), 8192),
                "teacherTrace",
                bounded(trace.toString(), 32768));
    }

    @Override
    public synchronized void executionFinished(TestIdentifier test, TestExecutionResult result) {
        if (!test.isTest()) {
            if (result.getStatus() != TestExecutionResult.Status.SUCCESSFUL) {
                containerFailures++;
                result.getThrowable()
                        .ifPresent(failure -> containerDiagnostics.add(diagnostic(failure)));
            }
            return;
        }
        String status = result.getStatus().name().toLowerCase(Locale.ROOT);
        outcomes.put(test.getUniqueId(), status);
        Map<String, Object> value = report(test);
        value.put("status", status.equals("successful") ? "passed" : status);
        result.getThrowable()
                .ifPresent(failure -> {
                    value.putAll(diagnostic(failure));
                    if (failure instanceof AssertionFailedError assertion) {
                        if (assertion.isExpectedDefined())
                            value.put(
                                    "expected",
                                    bounded(
                                            assertion.getExpected().getStringRepresentation(),
                                            8192));
                        if (assertion.isActualDefined())
                            value.put(
                                    "actual",
                                    bounded(assertion.getActual().getStringRepresentation(), 8192));
                    }
                    if (result.getStatus() == TestExecutionResult.Status.FAILED)
                        failureKinds.put(test.getUniqueId(), failureKind(failure));
                });
    }

    @Override
    public synchronized void reportingEntryPublished(TestIdentifier test, ReportEntry entry) {
        if (test.isTest())
            for (String key : List.of("expected", "actual"))
                if (entry.getKeyValuePairs().containsKey(key))
                    report(test).put(key, bounded(entry.getKeyValuePairs().get(key), 8192));
    }

    @Override
    public synchronized void testPlanExecutionFinished(TestPlan plan) {
        complete = true;
    }

    private synchronized Map<String, Object> result() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("complete", complete);
        result.put("registered", List.copyOf(registered));
        result.put("started", List.copyOf(started));
        result.put("outcomes", outcomes);
        result.put("failureKinds", failureKinds);
        result.put("cases", List.copyOf(cases.values()));
        result.put("grading", grading);
        result.put("classMaximums", classMaximums);
        result.put("containerFailures", containerFailures);
        result.put("containerDiagnostics", containerDiagnostics);
        return result;
    }

    public static void main(String[] args)
            throws IOException, org.json.simple.parser.ParseException {
        JSONObject params;
        try (Reader reader = Files.newBufferedReader(Path.of(args[0]))) {
            params = (JSONObject) new JSONParser().parse(reader);
        }
        List<String> students = new ArrayList<>();
        for (Object name : (JSONArray) params.get("student_classes")) students.add((String) name);
        PlatformJUnitAdapter listener = new PlatformJUnitAdapter(students);
        List<org.junit.platform.engine.discovery.ClassSelector> selectors = new ArrayList<>();
        for (Object name : (JSONArray) params.get("test_classes"))
            selectors.add(selectClass((String) name));
        Launcher launcher = LauncherFactory.create();
        launcher.execute(
                LauncherDiscoveryRequestBuilder.request()
                        .selectors(selectors)
                        .configurationParameter(
                                "junit.platform.stacktrace.pruning.enabled", "false")
                        .build(),
                listener);
        Files.writeString(
                Path.of((String) params.get("feedback_file")),
                JSONValue.toJSONString(listener.result()));
        System.exit(0);
    }
}
