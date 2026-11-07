"""Публичные перегрузки JUnit сохраняют результат, тип и отдельные случаи."""
import unittest
import test_plain_runtime as fixtures


class CourseDescriptors(unittest.TestCase):
    setUp = fixtures.PlainRuntimeTests.setUp
    run_job = fixtures.PlainRuntimeTests.run_job
    def test_course_descriptors_preserve_return_and_independent_failures(self) -> None:
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
        assert "score" in result
        self.assertEqual(result['score'], 0.2)
        self.assertEqual((result['counts']['executed'], result['counts']['passed'],
                          result['counts']['failed']), (5, 1, 4))
        correct = next(c for c in result['counts']['cases'] if 'correct()' in c['id'])
        self.assertEqual(correct['status'], 'passed')
        self.assertNotIn('checks', correct)



    def test_three_exact_overloads_keep_leaf_feedback(self) -> None:
        (self.job / 'tests/AnswerTest.java').write_text('''
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test void correct() {
  assertEquals(42, Integer.valueOf(Student.answer()));
  assertFalse(Student.answer()!=42, "PRIVATE_MESSAGE");
  assertArrayEquals(new char[]{'я'},new char[]{'я'});
 }
 @Test void wrongBoxed() {assertEquals(41,Integer.valueOf(Student.answer()));}
 @Test void nullBoxed() {assertEquals(42,(Integer)null);}
 @Test void wrongFalse() {assertFalse(Student.answer()==42,"PRIVATE_MESSAGE");}
 @Test void wrongChars() {assertArrayEquals(new char[]{'я'},new char[]{'ю'});}
}''')
        result = self.run_job()
        assert "score" in result
        self.assertEqual((result['counts']['executed'], result['counts']['passed'],
                          result['counts']['failed']), (5, 1, 4))
        self.assertEqual(result['score'], 0.2)
        correct = next(c for c in result['counts']['cases'] if 'correct()' in c['id'])
        self.assertEqual(correct['status'], 'passed')
        self.assertNotIn('checks', correct)
