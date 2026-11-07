"""Публичный результат проверки обычного Java задания без content inventories."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from platform_modules import load_java_grader
from grading_types import JavaGradingDescriptor, JavaOutcome

ROOT = Path(__file__).resolve().parents[1]
os.environ['PATH'] = '/usr/lib/jvm/java-25-openjdk/bin:' + os.environ['PATH']
grader = load_java_grader(ROOT / 'images/java25-grader/grade.py')

class PlainRuntimeTests(unittest.TestCase):
    job: Path
    config: JavaGradingDescriptor
    def setUp(self) -> None:
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

    def run_job(self) -> JavaOutcome:
        (self.job/'tests/grading-job.json').write_text(json.dumps(self.config))
        return grader.grade(self.job)

    def test_correct_answer_uses_standard_report_without_execution_inventory(self):
        result = self.run_job()
        assert "score" in result
        self.assertEqual(result['score'],1)
        assert 'counts' in result
        self.assertEqual(result['counts']['passed'],1)
        self.assertNotIn('executionEvidence',result)
        assert 'reportFormat' in result
        self.assertEqual(result['reportFormat'],'junit-listener')

    def test_student_assertion_is_runtime_failure(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){ throw new AssertionError("student"); } }')
        result = self.run_job()
        self.assertEqual(result['classification'],'student-runtime-failure')
        assert 'score' in result
        self.assertEqual(result['score'],0)
        assert 'counts' in result
        self.assertEqual(set(result['counts']['failureKinds'].values()),{'runtime'})

    def test_wrong_answer_keeps_assertion_feedback(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){ return 41; } }')
        result = self.run_job()
        self.assertEqual(result['classification'],'behavior-failure')
        assert 'score' in result
        self.assertEqual(result['score'],0)
        assert 'counts' in result
        case = result['counts']['cases'][0]
        self.assertEqual(case['expected'],'42')
        self.assertEqual(case['actual'],'41')

    def test_threshold_preserves_declared_junit_points(self):
        self.config['scoring']={'mode':'threshold','basis':'score','value':0.5}
        (self.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test @Tag("points=3") void heavy(){ assertEquals(0,Student.answer()); } @Test @Tag("points=1") void light(){ assertEquals(42,Student.answer()); } }')
        result=self.run_job()
        assert 'rawResult' in result and 'score' in result
        self.assertEqual(result['rawResult']['score'],0.25)
        assert 'score' in result
        self.assertEqual(result['score'],0)

    def test_dynamic_and_parameterized_cases_use_public_junit_ids(self):
        (self.job/'tests/AnswerTest.java').write_text('import java.util.stream.Stream; import org.junit.jupiter.api.*; import org.junit.jupiter.params.ParameterizedTest; import org.junit.jupiter.params.provider.ValueSource; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @ParameterizedTest @ValueSource(ints={41,42}) void rows(int n){assertEquals(n,Student.answer());} @TestFactory Stream<DynamicTest> generated(){return Stream.of(DynamicTest.dynamicTest("Динамический",()->assertEquals(42,Student.answer())));}}')
        result=self.run_job()
        assert 'counts' in result and 'score' in result
        self.assertEqual(result['counts']['executed'],3)
        self.assertEqual(result['score'],2/3)

    def test_successful_empty_factories_and_containers_are_not_leaf_cases(self):
        (self.job/'tests/AnswerTest.java').write_text('import java.util.stream.Stream; import org.junit.jupiter.api.*; import static org.junit.jupiter.api.Assertions.*; public class AnswerTest { @Test void answer(){assertEquals(42,Student.answer());} @TestFactory Stream<DynamicNode> empty(){return Stream.empty();} @TestFactory Stream<DynamicNode> container(){return Stream.of(DynamicContainer.dynamicContainer("empty",Stream.empty()));}}')
        result=self.run_job()
        assert 'score' in result and 'counts' in result
        self.assertEqual(result['score'],1)
        self.assertEqual(result['counts']['executed'],1)
        assert 'counts' in result
        self.assertEqual(result['counts']['passed'],1)

    def test_premature_jvm_exit_is_infrastructure(self):
        (self.job/'student/Student.java').write_text('public class Student { public static int answer(){System.exit(0);return 42;} }')
        with self.assertRaises(grader.GraderError): self.run_job()

    def test_compile_error_is_student_result(self):
        (self.job/'student/Student.java').write_text('not java')
        result = self.run_job()
        self.assertEqual(result['classification'],'student-compilation-failure')
        assert 'score' in result
        self.assertEqual(result['score'],0)

if __name__ == '__main__': unittest.main()
