import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.*;
import org.json.simple.JSONValue;
import org.prairielearn.feedback.PlatformJUnitAdapter;

public class InitializerOriginProbe {
    interface Call { void run() throws Throwable; }
    static Throwable observed(Call call) {
        try { call.run(); throw new AssertionError("missing failure"); }
        catch (Throwable failure) { return failure; }
    }
    static void bind(Object owner, String name, Object value) throws Exception {
        Field field=owner.getClass().getDeclaredField(name);
        field.setAccessible(true);field.set(owner,value);
    }
    public static void main(String[] args) throws Exception {
        var adapter=new PlatformJUnitAdapter();
        bind(adapter,"submissionMode","implementation");
        bind(adapter,"studentRoot",Path.of(args[0]).toRealPath());
        bind(adapter,"studentClasses",Set.of("StudentInit","StudentAssertion"));
        Method classify=PlatformJUnitAdapter.class.getDeclaredMethod("failureKind",Throwable.class);
        classify.setAccessible(true);
        Map<String,Throwable> failures=new LinkedHashMap<>();
        failures.put("student-first",observed(StudentInit::entry));
        failures.put("student-repeat",observed(StudentInit::entry));
        failures.put("trusted-first",observed(TrustedInit::entry));
        failures.put("trusted-repeat",observed(TrustedInit::entry));
        failures.put("trusted-missing",observed(TrustedMissing::entry));
        failures.put("junit-assertion",observed(()->org.junit.jupiter.api.Assertions.fail("trusted assertion")));
        failures.put("student-assertion",observed(StudentAssertion::entry));
        failures.put("invocation-student",new InvocationTargetException(failures.get("student-repeat")));
        failures.put("invocation-assertion",new InvocationTargetException(failures.get("junit-assertion")));
        failures.put("untyped-cause",new RuntimeException("trusted wrapper",failures.get("student-first")));
        failures.put("wrapper-cycle",new CycleInvocation());
        failures.put("wrapper-expanding",new ExpandingInvocation());
        Map<String,Map<String,Object>> result=new LinkedHashMap<>();
        for (var row:failures.entrySet()) {
            Throwable failure=row.getValue();
            Map<String,Object> item=new LinkedHashMap<>();
            item.put("kind",classify.invoke(adapter,failure));
            item.put("type",failure.getClass().getName());
            List<String> chain=new ArrayList<>();
            Set<Throwable> seen=Collections.newSetFromMap(new IdentityHashMap<>());
            for (Throwable cause=failure;cause!=null && chain.size()<20 && seen.add(cause);cause=cause.getCause())
                chain.add(cause.getClass().getSimpleName()+":"+Arrays.stream(cause.getStackTrace()).map(StackTraceElement::getClassName).limit(3).toList());
            item.put("chain",chain);result.put(row.getKey(),item);
        }
        System.out.println(JSONValue.toJSONString(result));
    }
}
class TrustedInit {
    static { if (true) throw new IllegalStateException("trusted initializer"); }
    static void entry() {}
}
class TrustedMissing { static void entry() { MissingTrusted.entry(); } }
class MissingTrusted { static void entry() {} }

class CycleInvocation extends InvocationTargetException {
    private static final long serialVersionUID = 1L;
    CycleInvocation() { super((Throwable)null); }
    @Override public Throwable getCause() { return this; }
}
class ExpandingInvocation extends InvocationTargetException {
    private static final long serialVersionUID = 1L;
    ExpandingInvocation() { super((Throwable)null); }
    @Override public Throwable getCause() { return new ExpandingInvocation(); }
}
