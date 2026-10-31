"""Числовые перегрузки сохраняют настоящий JUnit и закрытое сообщение."""

import test_assertion_feedback as af


class NumericMessages(af.ProductionCase):
    def test_character_equality_and_long_inequality_keep_leaf_points(self):
        (self.job / "tests/AnswerTest.java").write_text('''
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 @Test void correct(){
  assertEquals('a',(char)(Student.answer()+55));
  assertNotEquals(41L,(long)Student.answer());
 }
 @Test void wrong(){assertNotEquals(42L,(long)Student.answer());}
}''')
        result = self.run_job()
        self.assertEqual(result["score"], 0.5)
        self.assertEqual((result["counts"]["executed"], result["counts"]["passed"],
                          result["counts"]["failed"]), (2, 1, 1))
        correct = next(c for c in result["counts"]["cases"] if "correct()" in c["id"])
        self.assertEqual([c["delegated"] for c in correct["checks"]], ["returned", "returned"])
        wrong = next(c for c in result["counts"]["cases"] if "wrong()" in c["id"])
        self.assertEqual(len(wrong["checks"]), 1)
        self.assertEqual((wrong["checks"][0]["expected"], wrong["checks"][0]["actual"],
                          wrong["checks"][0]["delegated"]), ("42", "42", "threw"))

    def test_long_and_boolean_messages_preserve_the_real_delegate(self):
        (self.job / "tests/AnswerTest.java").write_text('''
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 static int messages;
 @Test void result(){
  assertEquals(42L,(long)Student.answer(),"PRIVATE_LONG_MESSAGE");
  assertTrue(Student.answer()==42,()->{messages++;return "PRIVATE_BOOLEAN_MESSAGE";});
  if(messages!=0)throw new AssertionError("eager supplier");
 }
}''')
        result = self.run_job()
        self.assertEqual(result["score"], 1)
        self.assertEqual((result["counts"]["executed"], result["counts"]["passed"]), (1, 1))
        checks = result["counts"]["cases"][0]["checks"]
        self.assertEqual(len(checks), 2)
        self.assertEqual([(c["expected"], c["actual"], c["delegated"]) for c in checks],
                         [("42", "42", "returned"), ("true", "true", "returned")])
        native = str(af.feedback(result, self.cfg))
        self.assertNotIn("PRIVATE_LONG_MESSAGE", native)
        self.assertNotIn("PRIVATE_BOOLEAN_MESSAGE", native)

    def test_numeric_tolerance_messages_delegate_without_eager_supplier(self):
        (self.job / "tests/AnswerTest.java").write_text('''
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 static int messages;
 static String message(){messages++;return "PRIVATE_NUMERIC_MESSAGE";}
 @Test void result(){
  assertEquals(42d,Student.answer(),0.01d,"PRIVATE_NUMERIC_MESSAGE");
  assertEquals(42d,Student.answer(),0.01d,AnswerTest::message);
  assertEquals(42f,Student.answer(),0.01f,"PRIVATE_NUMERIC_MESSAGE");
  assertEquals(42f,Student.answer(),0.01f,AnswerTest::message);
  assertArrayEquals(new double[]{42},new double[]{Student.answer()},0.01d,"PRIVATE_NUMERIC_MESSAGE");
  assertArrayEquals(new double[]{42},new double[]{Student.answer()},0.01d,AnswerTest::message);
  assertArrayEquals(new float[]{42},new float[]{Student.answer()},0.01f,"PRIVATE_NUMERIC_MESSAGE");
  assertArrayEquals(new float[]{42},new float[]{Student.answer()},0.01f,AnswerTest::message);
  if(messages!=0)throw new AssertionError("eager supplier");
 }
}''')
        result = self.run_job()
        self.assertEqual(result["score"], 1)
        self.assertEqual((result["counts"]["executed"], result["counts"]["passed"]), (1, 1))
        checks = result["counts"]["cases"][0]["checks"]
        self.assertEqual(len(checks), 8)
        self.assertTrue(all(check["delegated"] == "returned" for check in checks))
        self.assertTrue(all("допуск" in check["property"] for check in checks))
        self.assertNotIn("PRIVATE_NUMERIC_MESSAGE", str(af.feedback(result, self.cfg)))

    def test_failed_tolerance_keeps_leaf_score_and_one_lazy_message_call(self):
        (self.job / "tests/AnswerTest.java").write_text('''
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterAll;
import static org.junit.jupiter.api.Assertions.*;
public class AnswerTest {
 static int messages;
 @AfterAll static void once(){if(messages!=1)throw new AssertionError("supplier count");}
 @Test void result(){
  assertEquals(41d,Student.answer(),0.01d,()->{
   if(++messages!=1)throw new AssertionError("duplicate supplier");
   return "PRIVATE_FAILURE_MESSAGE";
  });
 }
}''')
        result = self.run_job()
        self.assertEqual(result["score"], 0)
        self.assertEqual((result["counts"]["executed"], result["counts"]["failed"]), (1, 1))
        self.assertEqual(result["counts"]["containerFailures"], 0)
        checks = result["counts"]["cases"][0]["checks"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["delegated"], "threw")
        self.assertEqual((checks[0]["expected"], checks[0]["actual"]), ("41.0", "42.0"))
        self.assertNotIn("PRIVATE_FAILURE_MESSAGE", str(af.feedback(result, self.cfg)))
