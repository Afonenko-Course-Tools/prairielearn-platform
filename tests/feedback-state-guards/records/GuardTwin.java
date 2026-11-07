public record GuardTwin(int id) {
  public static int accessors, strings;
  public int id() { accessors++; throw new AssertionError("foreign accessor"); }
  public String toString() { strings++; throw new AssertionError("foreign toString"); }
}
