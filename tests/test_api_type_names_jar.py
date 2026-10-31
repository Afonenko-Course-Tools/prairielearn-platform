"""Поиск типов в настоящем bound JAR не загружает студенческий код."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-25-openjdk")) / "bin"


class BoundJarTypeNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="bound-api-jar-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        sources = cls.work / "source"
        cls.classes = cls.work / "classes"
        cls.tools = cls.work / "tools"
        cls.classes.mkdir()
        cls.tools.mkdir()
        entries = {
            "GenericQueue.java": 'public class GenericQueue {static {System.setProperty("names.initialized","yes");}}',
            "a/GenericQueue.java": "package a; public class GenericQueue {}",
            "z/Holder.java": "package z; public class Holder {private static class GenericQueue {}}",
            "unlinked/GenericQueue.java": "package unlinked; public class GenericQueue extends Dependency {}",
            "unlinked/Dependency.java": "package unlinked; public class Dependency {}",
            "GenericQueueHelper.java": "class GenericQueueHelper {}",
            "OtherGenericQueue.java": "class OtherGenericQueue {}",
        }
        files = []
        for name, code in entries.items():
            path = sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code)
            files.append(str(path))
        cls.command("javac", "--release", "25", "-d", str(cls.classes), *files)
        cls.jar = cls.work / "student.jar"
        compiled = [p.relative_to(cls.classes).as_posix() for p in cls.classes.rglob("*.class")
                    if p.name != "Dependency.class"]
        jar_inputs = [arg for name in compiled for arg in ("-C", str(cls.classes), name)]
        cls.command("jar", "--create", "--file", str(cls.jar), *jar_inputs)
        empty = cls.work / "empty"
        empty.mkdir()
        cls.empty_jar = cls.work / "empty.jar"
        cls.command("jar", "--create", "--file", str(cls.empty_jar), "-C", str(empty), ".")
        side = cls.work / "side"
        side.mkdir()
        side_source = cls.work / "Side.java"
        side_source.write_text("package ambient; class GenericQueue {}")
        cls.command("javac", "--release", "25", "-d", str(side), str(side_source))
        cls.side_jar = cls.work / "side.jar"
        cls.command("jar", "--create", "--file", str(cls.side_jar), "-C", str(side), ".")
        versioned = cls.work / "versioned"
        versioned.mkdir()
        version_source = cls.work / "Versioned.java"
        version_source.write_text("package versioned; class GenericQueue {}")
        cls.command("javac", "--release", "25", "-d", str(versioned), str(version_source))
        cls.versioned_jar = cls.work / "versioned.jar"
        with zipfile.ZipFile(cls.versioned_jar, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\nMulti-Release: true\r\n\r\n")
            archive.write(versioned / "versioned/GenericQueue.class",
                          "META-INF/versions/25/versioned/GenericQueue.class")
        probe = cls.work / "TypeNamesJarProbe.java"
        probe.write_text('''package org.prairielearn.api;
import java.nio.file.*;
import java.util.List;
public class TypeNamesJarProbe {
  public static void main(String[] args) throws Exception {
    try (var api = new PlatformApiPrecheck.Api(Path.of(args[0]), Path.of(args[1]))) {
      if (args[2].equals("io")) {
        try { api.typeNames("GenericQueue"); throw new AssertionError("unsafe input accepted"); }
        catch (java.io.IOException expected) { System.out.print("IO"); return; }
      }
      if (args[2].equals("invalid")) {
        for (String name : new String[]{"", "../Secret", "a.b", "x/y", "String[]", "class", null}) {
          try { api.typeNames(name); throw new AssertionError("invalid name accepted"); }
          catch (IllegalArgumentException expected) {}
        }
      } else if (args[2].equals("versioned")) {
        if (!api.typeNames("GenericQueue").equals(List.of("versioned.GenericQueue")))
          throw new AssertionError("runtime jar candidates differ from loader");
        api.type("versioned.GenericQueue");
      } else if (args[2].equals("empty")) {
        if (!api.typeNames("GenericQueue").isEmpty()) throw new AssertionError("empty jar has candidates");
      } else {
        var names = api.typeNames("GenericQueue");
        if (!names.equals(List.of("GenericQueue", "a.GenericQueue", "unlinked.GenericQueue", "z.Holder$GenericQueue")))
          throw new AssertionError("wrong bound candidates: " + names);
        try { names.add("changed"); throw new AssertionError("mutable result"); }
        catch (UnsupportedOperationException expected) {}
        if (!api.typeNames("Absent").isEmpty()) throw new AssertionError("invented absent candidate");
        api.type("GenericQueue");
        if (System.getProperty("names.initialized") != null) throw new AssertionError("student initialized");
        if (args[2].equals("jar")) {
          try { api.type("unlinked.GenericQueue"); throw new AssertionError("omitted dependency linked"); }
          catch (PlatformApiPrecheck.Mismatch expected) {}
        }
      }
      System.out.print("OK");
    }
  }
}''')
        cls.library = ROOT / "runtime/java25-junit-v1/json-simple-1.1.1.jar"
        cls.command("javac", "--release", "25", "-cp", str(cls.library), "-d", str(cls.tools),
                    str(ROOT / "runtime/java25-junit-v1/PlatformApiPrecheck.java"), str(probe))

    @classmethod
    def command(cls, executable, *args):
        result = subprocess.run([str(JDK / executable), *args], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result

    def probe(self, bound, mode, expected="OK"):
        # Ambient candidate действительно есть в classpath процесса, но не в bound input.
        cp = os.pathsep.join(map(str, [self.tools, self.library, self.side_jar]))
        result = subprocess.run([str(JDK / "java"), "-cp", cp,
                                 "org.prairielearn.api.TypeNamesJarProbe", str(bound),
                                 str(self.work), mode], capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(expected, result.stdout)

    def test_bound_jar_exact_names_without_loading_initialization_or_ambient_scan(self):
        self.probe(self.jar, "jar")

    def test_existing_directory_discovery_is_preserved(self):
        self.probe(self.classes, "directory")

    def test_empty_jar_has_no_candidates(self):
        self.probe(self.empty_jar, "empty")

    def test_runtime_multi_release_names_agree_with_the_bound_loader(self):
        self.probe(self.versioned_jar, "versioned")

    def test_invalid_simple_names_remain_rejected(self):
        self.probe(self.jar, "invalid")

    def test_symlink_missing_and_corrupt_bound_inputs_are_io_failures(self):
        link = self.work / "linked.jar"
        link.symlink_to(self.jar)
        corrupt = self.work / "corrupt.jar"
        corrupt.write_bytes(b"not a jar")
        for path in [link, self.work / "missing.jar", corrupt]:
            with self.subTest(bound=path.name):
                self.probe(path, "io", "IO")
