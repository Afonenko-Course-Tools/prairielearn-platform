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
  static final ClassDesc ACCESS = ClassDesc.of("org.prairielearn.feedback.ProjectionAccess");
  static final String BRIDGE = "$pl$c3$component";
  static final MethodTypeDesc BRIDGE_TYPE =
      MethodTypeDesc.of(ConstantDescs.CD_Object, ConstantDescs.CD_int);
  static byte[] project(ClassFile cf, byte[] original, String name, Properties policy) {
    var model = cf.parse(original);
    var record = model.findAttribute(Attributes.record()).orElseThrow();
    var parts = record.components();
    if (parts.isEmpty() || parts.size() > 16 || !model.interfaces().isEmpty()
        || model.methods().stream().anyMatch(m -> m.methodName().stringValue().equals(BRIDGE)))
      throw new IllegalArgumentException("Reserved projection collision");
    List<String> schema = new ArrayList<>();
    for (var part : parts) {
      String fieldName = part.name().stringValue(), descriptor = part.descriptor().stringValue();
      if (fieldName.length() > 128
          || !(descriptor.startsWith("L") || descriptor.startsWith("[")
              || Set.of("I", "D", "J", "F", "Z", "B", "S", "C").contains(descriptor)))
        throw new IllegalArgumentException("Projection schema");
      var field = model.fields()
                      .stream()
                      .filter(f -> f.fieldName().equalsString(fieldName))
                      .findFirst()
                      .orElseThrow();
      if (!field.fieldType().equalsString(descriptor)
          || field.flags().flagsMask() != (ClassFile.ACC_PRIVATE | ClassFile.ACC_FINAL))
        throw new IllegalArgumentException("Projection field must be private final");
      schema.add(fieldName + ":" + descriptor);
    }
    byte[] result = cf.transformClass(model, new ClassTransform() {
      public void accept(ClassBuilder b, ClassElement e) {
        b.with(e);
      }
      public void atEnd(ClassBuilder b) {
        b.withInterfaceSymbols(ACCESS);
        b.withMethodBody(BRIDGE, BRIDGE_TYPE,
            ClassFile.ACC_PUBLIC | ClassFile.ACC_FINAL | ClassFile.ACC_SYNTHETIC, c -> {
              c.aload(0).invokestatic(ACCESS, "require",
                  MethodTypeDesc.of(ConstantDescs.CD_void, ConstantDescs.CD_Object), true);
              for (int i = 0; i < parts.size(); i++) {
                var part = parts.get(i);
                var next = c.newLabel();
                c.iload(1).loadConstant(i).if_icmpne(next).aload(0).getfield(
                    model.thisClass().asSymbol(), part.name().stringValue(),
                    part.descriptorSymbol());
                String d = part.descriptor().stringValue();
                String boxed = switch (d) {
                  case "I" -> "Integer";
                  case "D" -> "Double";
                  case "J" -> "Long";
                  case "F" -> "Float";
                  case "Z" -> "Boolean";
                  case "B" -> "Byte";
                  case "S" -> "Short";
                  case "C" -> "Character";
                  default -> null;
                };
                if (boxed != null) {
                  ClassDesc wrapper = ClassDesc.of("java.lang." + boxed);
                  c.invokestatic(
                      wrapper, "valueOf", MethodTypeDesc.of(wrapper, part.descriptorSymbol()));
                }
                c.areturn().labelBinding(next);
              }
              c.aconst_null().areturn();
            });
      }
    });
    if (!cf.verify(result).isEmpty())
      throw new IllegalStateException("Projection verifier");
    var post = cf.parse(result);
    List<String> afterParts =
        post.findAttribute(Attributes.record())
            .orElseThrow()
            .components()
            .stream()
            .map(p -> p.name().stringValue() + ":" + p.descriptor().stringValue())
            .toList();
    if (!afterParts.equals(schema) || !metadata(model).equals(metadata(post)))
      throw new IllegalStateException("Projection metadata changed");
    var bridge = post.methods()
                     .stream()
                     .filter(m -> m.methodName().equalsString(BRIDGE))
                     .findFirst()
                     .orElseThrow();
    var code = bridge.code().orElseThrow();
    List<Instruction> instructions = new ArrayList<>();
    Map<Label, Integer> labels = new IdentityHashMap<>();
    for (var element : code) {
      if (element instanceof LabelTarget target)
        labels.put(target.label(), instructions.size());
      if (element instanceof Instruction instruction)
        instructions.add(instruction);
    }
    int cursor = 0;
    expect(instructions.get(cursor++), Opcode.ALOAD_0);
    invoke(instructions.get(cursor++), ACCESS, "require",
        MethodTypeDesc.of(ConstantDescs.CD_void, ConstantDescs.CD_Object), true);
    for (int ordinal = 0; ordinal < parts.size(); ordinal++) {
      var part = parts.get(ordinal);
      expect(instructions.get(cursor++), Opcode.ILOAD_1);
      if (!(instructions.get(cursor++) instanceof ConstantInstruction constant)
          || !constant.constantValue().equals(ordinal))
        throw new IllegalStateException("Projection ordinal template");
      var branch = instructions.get(cursor++);
      expect(branch, Opcode.IF_ICMPNE);
      expect(instructions.get(cursor++), Opcode.ALOAD_0);
      var field = instructions.get(cursor++);
      expect(field, Opcode.GETFIELD);
      if (!(field instanceof FieldInstruction f)
          || !f.owner().asSymbol().equals(model.thisClass().asSymbol())
          || !f.name().equalsString(part.name().stringValue())
          || !f.typeSymbol().equals(part.descriptorSymbol()))
        throw new IllegalStateException("Projection field template");
      String boxed = switch (part.descriptor().stringValue()) {
        case "I" -> "Integer";
        case "D" -> "Double";
        case "J" -> "Long";
        case "F" -> "Float";
        case "Z" -> "Boolean";
        case "B" -> "Byte";
        case "S" -> "Short";
        case "C" -> "Character";
        default -> null;
      };
      if (boxed != null) {
        ClassDesc wrapper = ClassDesc.of("java.lang." + boxed);
        invoke(instructions.get(cursor++), wrapper, "valueOf",
            MethodTypeDesc.of(wrapper, part.descriptorSymbol()), false);
      }
      expect(instructions.get(cursor++), Opcode.ARETURN);
      if (!Objects.equals(labels.get(((BranchInstruction) branch).target()), cursor))
        throw new IllegalStateException("Projection branch template");
    }
    expect(instructions.get(cursor++), Opcode.ACONST_NULL);
    expect(instructions.get(cursor++), Opcode.ARETURN);
    if (cursor != instructions.size() || !code.exceptionHandlers().isEmpty()
        || bridge.flags().flagsMask()
            != (ClassFile.ACC_PUBLIC | ClassFile.ACC_FINAL | ClassFile.ACC_SYNTHETIC)
        || !bridge.methodTypeSymbol().equals(BRIDGE_TYPE))
      throw new IllegalStateException("Projection complete template");
    policy.setProperty("projection." + name, String.join("|", schema));
    policy.setProperty("projectionBridgeInput." + name, digest(original));
    policy.setProperty("projectionGuard." + name, "1");
    return result;
  }
  static void expect(Instruction instruction, Opcode opcode) {
    if (instruction.opcode() != opcode)
      throw new IllegalStateException("Projection opcode template");
  }
  static void invoke(
      Instruction instruction, ClassDesc owner, String name, MethodTypeDesc type, boolean iface) {
    if (!(instruction instanceof InvokeInstruction call) || call.opcode() != Opcode.INVOKESTATIC
        || !call.owner().asSymbol().equals(owner) || !call.name().equalsString(name)
        || !call.typeSymbol().equals(type) || call.isInterface() != iface)
      throw new IllegalStateException("Projection invoke template");
  }
  static List<String> metadata(ClassModel model) {
    List<String> result = new ArrayList<>();
    result.add(model.findAttribute(Attributes.sourceFile())
            .map(a -> a.sourceFile().stringValue())
            .orElse(""));
    result.add(model.findAttribute(Attributes.nestHost())
            .map(a -> a.nestHost().asInternalName())
            .orElse(""));
    model.findAttribute(Attributes.innerClasses())
        .ifPresent(a
            -> a.classes().forEach(i
                -> result.add(i.innerClass().asInternalName() + "|"
                    + i.outerClass().map(c -> c.asInternalName()).orElse("") + "|"
                    + i.innerName().map(n -> n.stringValue()).orElse("") + "|" + i.flagsMask())));
    return result;
  }
  static String digest(byte[] bytes) {
    try {
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }
  public static void main(String[] args) throws Exception {
    if (args[0].equals("reader")) {
      var model = ClassFile.of().parse(Path.of(args[1]));
      for (var method : model.methods())
        if (method.methodName().equalsString("readComponent")) {
          int bci = 0;
          for (var e : method.code().orElseThrow()) {
            if (e instanceof InvokeInstruction call
                && call.owner().asInternalName().equals(
                    "org/prairielearn/feedback/ProjectionAccess")
                && call.name().equalsString(BRIDGE)
                && call.type().equalsString("(I)Ljava/lang/Object;")) {
              Files.writeString(Path.of(args[2]), "readerBci=" + bci + "\n");
              return;
            }
            if (e instanceof Instruction instruction)
              bci += instruction.sizeInBytes();
          }
        }
      throw new IllegalStateException("Missing closed reader callsite");
    }
    Path root = Path.of(args[0]);
    Properties map = new Properties();
    boolean adapter = args.length > 3 && args[3].equals("adapter");
    Set<String> projections = args.length > 3 && !adapter ? Set.of(args[3].split(",")) : Set.of();
    Set<String> missing = new HashSet<>(projections);
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
          int bci = 0, invokeOrdinal = 0;
          for (var e : method.code().get()) {
            if (e instanceof InvokeInstruction)
              invokeOrdinal++;
            if (e instanceof InvokeInstruction call && call.opcode() == Opcode.INVOKESTATIC
                && call.owner().asInternalName().equals("org/junit/jupiter/api/Assertions"))
              originals.add(method.methodName() + "|" + method.methodType() + "|" + invokeOrdinal);
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
      if (!adapter && projections.contains(name)) {
        missing.remove(name);
        map.setProperty("projectionPre." + name, digest(Files.readAllBytes(file)));
        bytes = project(cf, bytes, name, map);
      }
      Files.write(file, bytes);
      map.setProperty((adapter ? "adapterClass." : "class.") + name,
          HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)));
      for (var method : cf.parse(bytes).methods())
        if (method.code().isPresent()) {
          int bci = 0, line = 0, ordinal = 0, invokeOrdinal = 0;
          for (var element : method.code().get()) {
            if (element instanceof InvokeInstruction)
              invokeOrdinal++;
            if (element instanceof LineNumber l)
              line = l.line();
            if (element instanceof InvokeInstruction call
                && (call.owner().asInternalName().equals("org/prairielearn/feedback/Assertions")
                        && originals.contains(
                            method.methodName() + "|" + method.methodType() + "|" + invokeOrdinal)
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
    if (!missing.isEmpty())
      throw new IllegalArgumentException("Missing qualified projection types: " + missing);
    try (var out = Files.newOutputStream(Path.of(args[2]))) {
      map.store(out, "F0 private exact output");
    }
  }
}
