"""Настоящие Gradle jar/run/test с единым production output и JDK25."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('gradle'), 'Нужен локальный Gradle')
class PlainGradleTests(unittest.TestCase):
    def test_ordinary_jar_run_and_test(self):
        with tempfile.TemporaryDirectory(prefix='plain-gradle-') as temporary:
            work=Path(temporary)
            for name in ('build.gradle','settings.gradle'):
                shutil.copyfile(ROOT/'runtime/gradle-jar-v1'/name,work/name)
            (work/'native-config.json').write_text(json.dumps({'artifact':'answer.jar','mainClass':'Student'}))
            (work/'src').mkdir()
            (work/'tests').mkdir()
            (work/'src/Student.java').write_text('public class Student { public static int answer(){return 42;} public static void main(String[] args){System.out.println(answer());}}')
            (work/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer(){assertEquals(42,Student.answer());}}')
            java_home=os.environ.get('JAVA_HOME') or str(Path(shutil.which('javac')).resolve().parents[1])
            environment={**os.environ,'JAVA_HOME':java_home,'GRADLE_USER_HOME':str(work/'gradle-home')}
            environment['PATH']=environment['JAVA_HOME']+'/bin:'+environment['PATH']
            (work/'gradle.properties').write_text('org.gradle.java.installations.auto-download=false\norg.gradle.java.installations.paths='+environment['JAVA_HOME']+'\norg.gradle.workers.max=2\norg.gradle.jvmargs=-Xmx128m -XX:ActiveProcessorCount=2\n')
            command=['gradle','--offline','--no-daemon','--console=plain','-PjunitJar='+str(ROOT/'runtime/java25-junit-v1/junit-platform-console-standalone-1.14.1.jar'),'jar','run','test']
            result=subprocess.run(command,cwd=work,env=environment,capture_output=True,text=True,timeout=35)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('\n42\n',result.stdout)
            report=(work/'build/test-results/test/TEST-AnswerTest.xml').read_text()
            self.assertIn('failures="0"',report)
            self.assertIn('tests="1"',report)
            jar=subprocess.run([environment['JAVA_HOME']+'/bin/java','-jar',str(work/'build/libs/answer.jar')],capture_output=True,text=True,timeout=3)
            self.assertEqual(jar.returncode,0,jar.stderr)
            self.assertEqual(jar.stdout.strip(),'42')
