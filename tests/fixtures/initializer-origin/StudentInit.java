public class StudentInit {
    static { if (true) throw new IllegalStateException("student initializer"); }
    public static void entry() {}
}
