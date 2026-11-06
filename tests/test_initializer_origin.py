"""Два реальных JVM обращения к ошибочному initializer через настоящий classifier."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class InitializerOrigin(unittest.TestCase):
    def test_repeated_student_initializer_preserves_origin_and_trusted_errors_stay_infra(self):
        bundle=ROOT/'runtime/java25-junit-v1'
        jars=os.pathsep.join(str(bundle/name) for name in [
            'junit-platform-console-standalone-1.14.1.jar','json-simple-1.1.1.jar'])
        fixture=ROOT/'tests/fixtures/initializer-origin'
        with tempfile.TemporaryDirectory(prefix='initializer-origin-') as temporary:
            root=Path(temporary);student=root/'student';trusted=root/'trusted'
            student.mkdir();trusted.mkdir()
            def compile(output, sources, classpath):
                run=subprocess.run([shutil.which('javac'),'-J-Xmx128m','--release','25','-encoding','UTF-8',
                    '-proc:none','-cp',classpath,'-d',str(output),*map(str,sources)],capture_output=True,text=True,timeout=45)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            compile(student,[fixture/'StudentInit.java',fixture/'StudentAssertion.java'],jars)
            source=bundle/'feedback/module'
            compile(trusted,[*source.joinpath('org').rglob('*.java'),fixture/'InitializerOriginProbe.java'],
                    os.pathsep.join([jars,str(student)]))
            (trusted/'MissingTrusted.class').unlink()
            run=subprocess.run([shutil.which('java'),'-Xmx128m','-cp',os.pathsep.join([str(trusted),str(student),jars]),
                'InitializerOriginProbe',str(student)],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            evidence=json.loads(run.stdout)
            print(json.dumps(evidence,ensure_ascii=False))
            self.assertEqual(evidence['student-first']['type'],'java.lang.ExceptionInInitializerError')
            self.assertEqual(evidence['student-repeat']['type'],'java.lang.NoClassDefFoundError')
            expected={'student-first':'runtime','student-repeat':'runtime','trusted-first':'infrastructure',
                      'trusted-repeat':'infrastructure','trusted-missing':'infrastructure',
                      'junit-assertion':'wrong-answer','student-assertion':'runtime',
                      'invocation-student':'runtime','invocation-assertion':'wrong-answer',
                      'untyped-cause':'infrastructure','wrapper-cycle':'infrastructure',
                      'wrapper-expanding':'infrastructure'}
            for name,kind in expected.items():
                with self.subTest(case=name):self.assertEqual(evidence[name]['kind'],kind,evidence[name])


if __name__=='__main__':unittest.main()
