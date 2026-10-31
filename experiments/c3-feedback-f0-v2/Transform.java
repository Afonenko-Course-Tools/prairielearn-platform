import java.lang.classfile.*;
import java.lang.classfile.attribute.*;
import java.lang.classfile.instruction.*;
import java.lang.constant.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Конечный transform только выбранных F0 sites, без загрузки тестируемого кода. */
public final class Transform {
  static final ClassDesc FACADE = ClassDesc.of("org.prairielearn.feedback.Assertions");
  public static void main(String[] args) throws Exception {
    Path root = Path.of(args[0]);
    Properties map = new Properties();
    boolean adapter = args.length > 3;
    Set<String> supported = new HashSet<>();
    var facade = ClassFile.of().parse(Path.of(args[1]));
    for (var method : facade.methods())
      supported.add(method.methodName().stringValue() + method.methodType().stringValue());
    for (Path file :
        Files.walk(root).filter(p -> p.toString().endsWith(".class")).sorted().toList()) {
      var cf = ClassFile.of();
      var model = cf.parse(file);
      String name = model.thisClass().asInternalName().replace('/', '.');
      String source = model.findAttribute(Attributes.sourceFile())
                          .map(a -> a.sourceFile().stringValue())
                          .orElse("unknown.java");
      Set<String> originals = new HashSet<>();
      for (var method : model.methods())
        if (method.code().isPresent()) {
          int bci = 0;
          for (var e : method.code().get()) {
            if (e instanceof InvokeInstruction call && call.opcode() == Opcode.INVOKESTATIC
                && call.owner().asInternalName().equals("org/junit/jupiter/api/Assertions"))
              originals.add(method.methodName() + "|" + method.methodType() + "|" + bci);
            if (e instanceof Instruction instruction)
              bci += instruction.sizeInBytes();
          }
        }
      byte[] bytes = adapter
          ? Files.readAllBytes(file)
          : cf.transformClass(model, ClassTransform.transformingMethodBodies((builder, element) -> {
              if (element instanceof InvokeInstruction call && call.opcode() == Opcode.INVOKESTATIC
                  && call.owner().asInternalName().equals("org/junit/jupiter/api/Assertions")
                  && !adapter) {
                if (!supported.contains(call.name().stringValue() + call.type().stringValue()))
                  throw new IllegalArgumentException("Unsupported exact descriptor: " + call);
                builder.invokestatic(FACADE, call.name().stringValue(), call.typeSymbol());
              } else
                builder.with(element);
            }));
      if (!adapter && !cf.verify(bytes).isEmpty())
        throw new IllegalStateException("Verifier rejected " + name);
      Files.write(file, bytes);
      map.setProperty((adapter ? "adapterClass." : "class.") + name,
          HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)));
      for (var method : cf.parse(bytes).methods())
        if (method.code().isPresent()) {
          int bci = 0, line = 0, ordinal = 0;
          for (var element : method.code().get()) {
            if (element instanceof LineNumber l)
              line = l.line();
            if (element instanceof InvokeInstruction call
                && (call.owner().asInternalName().equals("org/prairielearn/feedback/Assertions")
                        && originals.contains(
                            method.methodName() + "|" + method.methodType() + "|" + bci)
                    || adapter
                        && call.owner().asInternalName().equals(
                            "org/prairielearn/feedback/Gate"))) {
              map.setProperty((adapter ? "controlsite." : "site.") + name + "|"
                      + method.methodName() + "|" + method.methodType() + "|" + bci,
                  source + ":" + line + ":" + (++ordinal) + "|" + call.name() + "|" + call.type());
            }
            if (element instanceof Instruction instruction)
              bci += instruction.sizeInBytes();
          }
        }
    }
    try (var out = Files.newOutputStream(Path.of(args[2]))) {
      map.store(out, "F0 private exact output");
    }
  }
}
