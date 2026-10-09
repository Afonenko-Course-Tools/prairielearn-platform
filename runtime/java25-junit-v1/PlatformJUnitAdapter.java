import java.lang.reflect.*;
import java.io.*;
import org.json.simple.parser.JSONParser;
import java.nio.file.*;
import java.util.*;
import org.json.simple.*;
import org.junit.platform.launcher.*;
import org.junit.platform.engine.*;
import org.junit.platform.launcher.core.*;

/** Adapts the unchanged official autograder's /grade main to explicit roots. */
public final class PlatformJUnitAdapter implements TestExecutionListener {
 private final Map<String,String> outcomes=new TreeMap<>();
 private int discovered, executed, passed, failed, skipped, aborted;
 private int containerFailures;
 private TestPlan plan;
 public synchronized void testPlanExecutionStarted(TestPlan plan) { this.plan=plan;discovered=(int)plan.countTestIdentifiers(TestIdentifier::isTest); }
 public synchronized void dynamicTestRegistered(TestIdentifier test) { if(test.isTest()) discovered++; }
 public synchronized void executionStarted(TestIdentifier test) { if(test.isTest()) executed++; }
 public synchronized void executionSkipped(TestIdentifier test,String reason) {
  Set<TestIdentifier> skippedTests=new HashSet<>();
  if(test.isTest())skippedTests.add(test);
  else if(plan!=null)for(TestIdentifier child:plan.getDescendants(test))if(child.isTest())skippedTests.add(child);
  for(TestIdentifier child:skippedTests)if(outcomes.putIfAbsent(child.getUniqueId(),"skipped")==null)skipped++;
 }
 public synchronized void executionFinished(TestIdentifier test,TestExecutionResult result) {
  if(!test.isTest()) {if(result.getStatus()==TestExecutionResult.Status.FAILED)containerFailures++;return;}
  String status=result.getStatus().name().toLowerCase(Locale.ROOT);outcomes.put(test.getUniqueId(),status);
  switch(result.getStatus()) {case SUCCESSFUL:passed++;break;case FAILED:failed++;break;case ABORTED:aborted++;break;}
 }
 @SuppressWarnings("unchecked")
 public static void main(String[] args) throws Exception {
  Path parameterFile=Path.of(args[0]);
  JSONObject params;
  try(Reader reader=Files.newBufferedReader(parameterFile)){params=(JSONObject)new JSONParser().parse(reader);}
  Files.delete(parameterFile);
  String resultFile=(String)params.get("results_file"), countsFile=(String)params.get("counts_file"), signature=(String)params.get("signature");
  String[] testClasses=(String[])((JSONArray)params.get("test_classes")).toArray(new String[0]);
  Object official=Class.forName("JUnitAutograder").getConstructor().newInstance();
  Field files=official.getClass().getDeclaredField("testClasses");files.setAccessible(true);files.set(official,testClasses);
  Field output=official.getClass().getDeclaredField("resultsFile");output.setAccessible(true);output.set(official,resultFile);
  PlatformJUnitAdapter listener=new PlatformJUnitAdapter();
  Field launcher=official.getClass().getDeclaredField("launcher");launcher.setAccessible(true);
  ((Launcher)launcher.get(official)).registerTestExecutionListeners(listener);
  official.getClass().getMethod("runTests").invoke(official);
  Method save=official.getClass().getDeclaredMethod("saveResults",String.class);save.setAccessible(true);save.invoke(official,signature);
  JSONObject counts=new JSONObject();counts.put("discovered",listener.discovered);counts.put("executed",listener.executed);counts.put("passed",listener.passed);counts.put("failed",listener.failed);counts.put("skipped",listener.skipped);counts.put("aborted",listener.aborted);counts.put("containerFailures",listener.containerFailures);counts.put("outcomes",listener.outcomes);counts.put("signature",signature);
  Files.writeString(Path.of(countsFile),counts.toJSONString());
  System.exit(0);
 }
}
