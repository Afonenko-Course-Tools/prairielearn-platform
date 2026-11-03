"""Точные JUnit ABI: настоящий javac25/Transform/delegate без grader и контейнера."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ExactOverloads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='junit-abi-source-')
        cls.base = Path(cls.temp.name)
        cls.jar = Path(os.environ.get('JUNIT_STANDALONE', ROOT/'runtime/java25-junit-v1/junit-platform-console-standalone-1.14.1.jar'))
        if not cls.jar.is_file():
            raise RuntimeError('Нужен закреплённый JUnit standalone1.14.1; сеть не используется')
        cls.jdk = Path(os.environ.get('JAVA_HOME', '/usr/lib/jvm/java-25-openjdk'))/'bin'
        cls.facade = cls.base/'facade'
        cls.helper = cls.base/'helper'
        cls.facade.mkdir(); cls.helper.mkdir()
        sources = sorted((ROOT/'runtime/java25-junit-v1/feedback/module').rglob('*.java'))
        cls.invoke(['javac', '--release', '25', '--module-path', str(cls.jar), '-d', str(cls.facade), *map(str, sources)])
        cls.invoke(['javac', '--release', '25', '-d', str(cls.helper), str(ROOT/'runtime/java25-junit-v1/feedback/Transform.java')])
        (cls.facade/'org/prairielearn/feedback/internal/policy.properties').write_text('# inert Source control, no live leaf\n')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def invoke(cls, args, check=True):
        argv = [str(cls.jdk/args[0]), *args[1:]]
        return subprocess.run(argv, capture_output=True, text=True, timeout=45, check=check)

    def compile_fixture(self, name, body):
        root = self.base/name; root.mkdir()
        source = self.base/(name+'.java'); source.write_text(body)
        self.invoke(['javac', '--release', '25', '-cp', str(self.jar), '-d', str(root), str(source)])
        return root

    def transform(self, root):
        return self.invoke(['java', '-cp', os.pathsep.join(map(str,(self.helper,self.jar))), 'Transform', str(root),
                         str(self.facade/'org/prairielearn/feedback/Assertions.class'),
                         str(root/'sites.properties')], check=False)

    def test_exact_three_descriptors_delegate_success_failure_and_null(self):
        root = self.compile_fixture('OverloadFixture', '''
import static org.junit.jupiter.api.Assertions.*;
public class OverloadFixture {
 static int observedFailures;
 static void fails(Runnable body) {
  try {body.run(); throw new IllegalStateException("missing failure");}
  catch(org.opentest4j.AssertionFailedError expected) {observedFailures++;}
 }
 public static void main(String[] args) {
  assertEquals(42, Integer.valueOf(42));
  assertFalse(false, "PRIVATE_MESSAGE");
  assertArrayEquals(new char[]{'я'}, new char[]{'я'});
  fails(()->assertEquals(42, Integer.valueOf(43)));
  fails(()->assertEquals(42, (Integer)null));
  fails(()->assertFalse(true, "PRIVATE_MESSAGE"));
  fails(()->assertArrayEquals(new char[]{'я'}, new char[]{'ю'}));
  fails(()->assertArrayEquals(new char[]{'я'}, (char[])null));
  if(observedFailures!=5)throw new IllegalStateException("changed delegation");
  System.out.println("EXACT_OVERLOADS_OK");
 }
}''')
        transformed = self.transform(root)
        self.assertEqual(transformed.returncode, 0, transformed.stderr)
        sites = (root/'sites.properties').read_text()
        for descriptor in ('(ILjava/lang/Integer;)V', '(ZLjava/lang/String;)V', '([C[C)V'):
            self.assertIn(descriptor, sites)
        result = self.invoke(['java', '-cp', os.pathsep.join(map(str, (root, self.facade, self.jar))), 'OverloadFixture'])
        self.assertEqual(result.stdout.strip(), 'EXACT_OVERLOADS_OK')

    def test_unknown_exact_descriptor_remains_refused(self):
        root = self.compile_fixture('UnsupportedFixture', '''
import static org.junit.jupiter.api.Assertions.*;
public class UnsupportedFixture {static void check(){assertArrayEquals(new boolean[]{true},new boolean[]{true});}}
''')
        result = self.transform(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported exact descriptor', result.stderr)
        self.assertFalse((root/'sites.properties').exists())
