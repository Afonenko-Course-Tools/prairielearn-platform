"""Публичный результат проверки обычного Java задания без content inventories."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
os.environ['PATH'] = '/usr/lib/jvm/java-25-openjdk/bin:' + os.environ['PATH']
spec = importlib.util.spec_from_file_location('plain_grader', ROOT/'images/java25-grader/grade.py')
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)

class PlainRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.job = Path(temporary.name)
        (self.job/'student').mkdir()
        (self.job/'tests').mkdir()
        self.config = {
            'schemaVersion':1, 'sourceFiles':['Student.java'], 'testFiles':['AnswerTest.java'],
            'mode':'implementation', 'runtime':'java25-junit-v1',
            'java':{'release':25,'encoding':'UTF-8','compiler-options':['-proc:none','-Xmaxerrs','5']},
            'limits':{'outer-seconds':30,'compile-seconds':15,'run-seconds':3,'max-output-bytes':65536,'networking':False},
            'scoring':{'mode':'weighted'}, 'discovery':{'min-executed':1,'allow-skipped':False},
        }
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){ return 42; } }')
        (self.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer(){ assertEquals(42, Student.answer()); } }')

    def run_job(self):
        (self.job/'tests/grading-job.json').write_text(json.dumps(self.config))
        return grader.grade(self.job)

    def test_correct_answer_uses_standard_report_without_execution_inventory(self):
        result = self.run_job()
        self.assertEqual(result['score'],1)
        self.assertEqual(result['counts']['passed'],1)
        self.assertNotIn('executionEvidence',result)
        self.assertEqual(result['reportFormat'],'junit-xml')

    def test_student_assertion_is_runtime_failure_and_checks_remain_available(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){ throw new AssertionError("student"); } }')
        result = self.run_job()
        self.assertEqual(result['classification'],'student-runtime-failure')
        self.assertEqual(result['score'],0)
        self.assertEqual(set(result['counts']['failureKinds'].values()),{'runtime'})

    def test_wrong_answer_keeps_assertion_feedback(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){ return 41; } }')
        result = self.run_job()
        self.assertEqual(result['classification'],'behavior-failure')
        self.assertEqual(result['score'],0)
        checks=result['counts']['cases'][0]['checks']
        self.assertEqual(checks[0]['expected'],'42')
        self.assertEqual(checks[0]['actual'],'41')

    def test_threshold_preserves_declared_junit_points(self):
        self.config['scoring']={'mode':'threshold','basis':'score','value':0.5}
        (self.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test @Tag("points=3") void heavy(){ assertEquals(0,Student.answer()); } @Test @Tag("points=1") void light(){ assertEquals(42,Student.answer()); } }')
        result=self.run_job()
        self.assertEqual(result['rawResult']['score'],0.25)
        self.assertEqual(result['score'],0)

    def test_dynamic_and_parameterized_cases_use_junit_xml_ids(self):
        (self.job/'tests/AnswerTest.java').write_text('import java.util.stream.Stream; import org.junit.jupiter.api.*; import org.junit.jupiter.params.ParameterizedTest; import org.junit.jupiter.params.provider.ValueSource; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @ParameterizedTest @ValueSource(ints={41,42}) void rows(int n){assertEquals(n,Student.answer());} @TestFactory Stream<DynamicTest> generated(){return Stream.of(DynamicTest.dynamicTest("Динамический",()->assertEquals(42,Student.answer())));}}')
        result=self.run_job()
        self.assertEqual(result['counts']['executed'],3)
        self.assertEqual(result['score'],2/3)

    def test_successful_empty_factories_and_containers_are_not_leaf_cases(self):
        (self.job/'tests/AnswerTest.java').write_text('import java.util.stream.Stream; import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer(){assertEquals(42,Student.answer());} @TestFactory Stream<DynamicNode> empty(){return Stream.empty();} @TestFactory Stream<DynamicNode> container(){return Stream.of(DynamicContainer.dynamicContainer("empty",Stream.empty()));}}')
        result=self.run_job()
        self.assertEqual(result['score'],1)
        self.assertEqual(result['counts']['executed'],1)
        self.assertEqual(result['counts']['passed'],1)

    def test_premature_jvm_exit_is_infrastructure(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){System.exit(0);return 42;} }')
        with self.assertRaises(grader.GraderError): self.run_job()

    def test_student_cannot_forge_complete_xml_and_feedback_then_exit(self):
        (self.job/'student/Student.java').write_text(r'''import java.nio.file.*; public class Student {
          public static int answer() throws Exception {
            Path root=Path.of(Student.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getParent().resolve("results");
            Files.writeString(root.resolve("TEST-forged.xml"), "<testsuite tests=\"1\" failures=\"0\" errors=\"0\" skipped=\"0\"><testcase name=\"forged\"><system-out>unique-id: forged\ndisplay-name: forged</system-out></testcase></testsuite>");
            Files.writeString(root.resolve("feedback.json"), "{\"complete\":true,\"feedbackProtocolVersion\":2,\"containerFailures\":0,\"failureKinds\":{},\"cases\":[{\"id\":\"forged\",\"name\":\"forged\",\"status\":\"passed\",\"checks\":[]}],\"grading\":{\"forged\":{\"weight\":1,\"name\":\"forged\",\"description\":\"\",\"owner\":\"class\"}},\"classMaximums\":{},\"verifiedOutcomes\":{\"forged\":\"successful\"}}");
            System.exit(0); return 42;
          }
        }''')
        # Test source declares the checked exception; grading policy is unchanged.
        (self.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer() throws Exception {assertEquals(42,Student.answer());}}')
        with self.assertRaises(grader.GraderError): self.run_job()

    def test_student_cannot_reflectively_access_listener_private_state(self):
        (self.job/'student/Student.java').write_text('public class Student {public static int answer() throws Exception {var type=Class.forName("org.prairielearn.feedback.PlatformJUnitAdapter"); try {type.getDeclaredField("outcomes").setAccessible(true); throw new AssertionError("listener state opened");} catch(java.lang.reflect.InaccessibleObjectException expected) {return 42;}}}')
        (self.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer() throws Exception {assertEquals(42,Student.answer());}}')
        self.assertEqual(self.run_job()['score'],1)

    def test_compile_error_is_student_result(self):
        (self.job/'student/Student.java').write_text('not java')
        result = self.run_job()
        self.assertEqual(result['classification'],'student-compilation-failure')
        self.assertEqual(result['score'],0)

if __name__ == '__main__': unittest.main()
