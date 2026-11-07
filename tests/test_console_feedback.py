"""Канонический console helper; классификация не зависит от текста stderr."""
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from json_boundary import json_object
import test_grading_job as fixtures
import test_plain_image as image_fixtures
from test_student_feedback import feedback


@unittest.skipUnless(os.environ.get('JAVA_CONSOLE_SUPPORT'), 'Нужен канонический JAVA_CONSOLE_SUPPORT')
class ConsoleFeedback(unittest.TestCase):
    def fixture(self) -> tuple[fixtures.JUnitJob, Path]:
        fixture = fixtures.JUnitJob()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        helper = fixture.job/'tests/coursesupport/JavaProcess.java'
        helper.parent.mkdir()
        shutil.copyfile(os.environ['JAVA_CONSOLE_SUPPORT'], helper)
        config = fixture.cfg
        tests = config['testFiles']
        tests.append('coursesupport/JavaProcess.java')
        fixture.cfg = config
        return fixture, helper

    def test_nested_process_failures_are_typed_and_nonzero_exit_is_allowed(self) -> None:
        for student, kind in [
            ('throw new IllegalStateException("CLOSED_CONSOLE_EXCEPTION");', 'runtime'),
            ('while(true){}', 'timeout'),
            ('while(true){System.out.print("CLOSED_OUTPUT_CANARY".repeat(1024));}', 'output-limit'),
            ('System.out.print("WRONG_PUBLIC");', 'wrong-answer'),
            ('System.out.print("PUBLIC_OK");System.exit(7);', 'success')]:
            with self.subTest(kind=kind):
                fixture, _ = self.fixture()
                config = fixture.cfg
                limits = config['limits']
                limits.update({'outer-seconds': 45, 'run-seconds': 20})
                config['limits'] = limits
                fixture.cfg = config
                (fixture.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+student+'}}')
                (fixture.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void console() throws Exception {var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");assertEquals("PUBLIC_OK",r.stdout());}}')
                result = fixture.run_job()
                native = feedback.student_result(result, fixture.cfg)
                self.assertEqual(native['feedback']['kind'], kind, result)
                self.assertNotIn('CLOSED_', json.dumps(native))
                expected_kind = {'runtime':'runtime','timeout':'timeout','output-limit':'output-limit','wrong-answer':'wrong-answer'}.get(kind)
                if expected_kind:
                    assert 'counts' in result
                    self.assertEqual(set(result['counts']['failureKinds'].values()), {expected_kind})
                import test_review_receipts as review
                bound = json_object(review.result())
                bound.update(json_object(result))
                bound['backend'] = 'host'
                review.g.validate('check-result', bound)
                if kind == 'success':
                    assert 'score' in result
                    self.assertEqual(result['score'], 1)

    def test_ordinary_junit_typed_failure_before_report_is_executed(self) -> None:
        for source, kind in [
            ('throw new IllegalStateException("CLOSED_EARLY_RUNTIME");', 'runtime'),
            ('while(true){}', 'timeout'),
            ('while(true){System.out.print("CLOSED_EARLY_OUTPUT".repeat(1024));}', 'output-limit')]:
            with self.subTest(kind=kind):
                fixture, _ = self.fixture()
                config = fixture.cfg
                limits = config['limits']
                limits['run-seconds'] = 20
                config['limits'] = limits
                fixture.cfg = config
                (fixture.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+source+'}}')
                (fixture.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;import java.util.Map;public class AnswerTest {@Test void console(TestReporter reporter)throws Exception{var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");reporter.publishEntry(Map.of("expected","PUBLIC_OK","actual",r.stdout()));assertEquals("PUBLIC_OK",r.stdout());}}')
                result = fixture.run_job()
                native = feedback.student_result(result, fixture.cfg)
                details = native['feedback']
                self.assertEqual(details['kind'], kind)
                assert 'cases' in details
                actual = details['cases'][0]
                self.assertEqual(actual['status'], 'failed')
                self.assertNotIn('actual', actual)
                self.assertNotIn('CLOSED_', json.dumps(native))
                assert 'counts' in result
                self.assertEqual(result['counts']['executed'], 1)
                assert 'tests' in native
                native_tests = native['tests']
                self.assertEqual(len(native_tests), 1)

    def test_missing_companion_or_wrong_origin_is_infrastructure(self) -> None:
        for mode in ['missing-companion', 'origin']:
            with self.subTest(mode=mode):
                fixture, helper = self.fixture()
                if mode == 'missing-companion':
                    helper.write_text(helper.read_text().replace('StudentTimeout', 'MissingTimeout'))
                original = json.dumps

                def private_parameter(value: object) -> str:
                    if mode == 'origin':
                        try:
                            parameter = json_object(value)
                        except ValueError:
                            parameter = None
                        if parameter is not None and 'trusted_console_support_root' in parameter:
                            value = {**parameter, 'trusted_console_support_root': str(fixture.job)}
                    return original(value)

                with patch.object(json, 'dumps', side_effect=private_parameter):
                    with self.assertRaises(fixtures.grader.GraderError):
                        fixture.run_job()

    def test_student_owner_or_inner_binary_collision_cannot_be_trusted(self) -> None:
        fixture, helper = self.fixture()
        student = fixture.job/'student/coursesupport/JavaProcess.java'
        student.parent.mkdir()
        shutil.copyfile(helper, student)
        config = fixture.cfg
        sources = config['sourceFiles']
        sources.append('coursesupport/JavaProcess.java')
        fixture.cfg = config
        result = fixture.run_job()
        self.assertEqual(result['classification'], 'unsafe-submission')
        self.assertNotIn('counts', result)

    def test_similar_assertion_name_or_text_is_not_typed_failure(self) -> None:
        fixture, _ = self.fixture()
        (fixture.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;public class AnswerTest {static final class StudentTimeout extends AssertionError {} @Test void wrong(){throw new StudentTimeout();}}')
        result = fixture.run_job()
        self.assertEqual(result['classification'], 'behavior-failure')
        assert 'counts' in result
        self.assertEqual(set(result['counts']['failureKinds'].values()), {'wrong-answer'})

    def test_student_descriptor_cannot_supply_trusted_origin_marker(self) -> None:
        fixture, _ = self.fixture()
        with patch.dict(fixture.cfg, {'trusted_console_support_root': str(fixture.job)}):
            with self.assertRaises(fixtures.grader.GraderError):
                fixture.run_job()


@unittest.skipUnless(os.environ.get('PL_TEST_IMAGE') and os.environ.get('JAVA_CONSOLE_SUPPORT'), 'Нужны immutable образ и канонический console source')
class ConsoleContainerFeedback(unittest.TestCase):
    def test_official_nested_process_runtime_and_legal_exit7(self) -> None:
        for source, kind in [
            ('throw new IllegalStateException("CLOSED_NESTED_CONTAINER");', 'runtime'),
            ('System.out.print("PUBLIC_OK");System.exit(7);', 'success')]:
            with self.subTest(kind=kind):
                owner = ConsoleFeedback()
                self.addCleanup(owner.doCleanups)
                fixture, _ = owner.fixture()
                (fixture.job/'student/Student.java').write_text('public class Student {public static void main(String[] args){'+source+'}}')
                (fixture.job/'tests/AnswerTest.java').write_text('import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;public class AnswerTest {@Test void console(org.junit.jupiter.api.TestReporter reporter)throws Exception{var r=coursesupport.JavaProcess.runCheckingUncaught(Class.forName("Student"),"");reporter.publishEntry(java.util.Map.of("expected","PUBLIC_OK","actual",r.stdout()));assertEquals("PUBLIC_OK",r.stdout());}}')
                image_test = image_fixtures.PlainImageTests()
                self.addCleanup(image_test.doCleanups)
                image_test.job = fixture.job
                image_test.config = fixture.cfg
                limits = image_test.config['limits']
                limits['run-seconds'] = 15
                image_test.config['limits'] = limits
                run, result = image_test.invoke(cpus='0.9', verification=False)
                self.assertEqual(run.returncode, 0, run.stderr)
                details = json_object(result['feedback'])
                self.assertEqual(details['kind'], kind)
                self.assertNotIn('CLOSED_', json.dumps(result) + run.stdout + run.stderr)
                cases = details['cases']
                assert isinstance(cases, list)
                case = json_object(cases[0])
                self.assertEqual(case['status'], 'failed' if kind == 'runtime' else 'passed')
                self.assertNotIn('publicCases', details)
