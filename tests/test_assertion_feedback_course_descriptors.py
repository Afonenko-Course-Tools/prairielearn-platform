"""Перегрузки из настоящего корпуса: delegate, возвращаемый тип и leaf feedback."""
import test_assertion_feedback as af


class CourseDescriptors(af.ProductionCase):
    def test_course_descriptors_preserve_return_and_independent_failures(self):
        (self.job / 'tests/AnswerTest.java').write_text('''
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test void correct() {
  assertNotEquals((Object) "other", (Object) Integer.valueOf(Student.answer()));
  assertNotEquals(41, Student.answer());
  assertArrayEquals(new long[]{42}, new long[]{Student.answer()});
  Integer value = assertInstanceOf(Integer.class, (Object) Student.answer());
  if(value.intValue() != 42) throw new AssertionError("lost typed return");
 }
 @Test void wrongObject() { assertNotEquals((Object) 42, (Object) Student.answer()); }
 @Test void wrongInt() { assertNotEquals(42, Student.answer()); }
 @Test void wrongArray() { assertArrayEquals(new long[]{41},new long[]{Student.answer()}); }
 @Test void wrongType() { assertInstanceOf(String.class,(Object) Student.answer()); }
}''')
        result = self.run_job()
        self.assertEqual(result['score'], 0.2)
        self.assertEqual((result['counts']['executed'], result['counts']['passed'],
                          result['counts']['failed']), (5, 1, 4))
        correct = next(c for c in result['counts']['cases'] if 'correct()' in c['id'])
        self.assertEqual([c['delegated'] for c in correct['checks']], ['returned'] * 4)
        for case in result['counts']['cases']:
            if case is not correct:
                self.assertEqual([c['delegated'] for c in case['checks']], ['threw'])

