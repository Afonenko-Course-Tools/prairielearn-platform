"""Перегрузки JUnit сохраняют аргументы, делегирование и границы native feedback."""

import json
from collections.abc import Sequence
import unittest

import test_assertion_feedback as af

feedback = af.feedback


class AssertionMessageOverloads(af.JobCase):

    def source(self, methods: str, extra: str = "") -> None:
        (self.job / "tests/AnswerTest.java").write_text(
            "import org.junit.jupiter.api.*;import static org.junit.jupiter.api.Assertions.*;"
            "public class AnswerTest {" + extra + methods + "}"
        )

    def test_long_array_string_message_reaches_native_as_one_leaf(self) -> None:
        self.source('''@Test @DisplayName("Длинные целые") void arrays(){
          assertArrayEquals(new long[]{1,2},new long[]{1,3},"PRIVATE_ARRAY_MESSAGE");
        }''')
        result = self.run_job()
        assert "score" in result
        self.assertEqual((af.result_counts(result)["executed"], result["score"]), (1, 0))
        checks = af.case_checks(af.result_counts(result)["cases"][0])
        self.assertEqual(
            [(c["expected"], c["actual"], c["delegated"]) for c in checks],
            [("[1, 2]", "[1, 3]", "threw")],
        )
        native = feedback(result, self.cfg)
        self.assertEqual((af.public_score(native), len(af.public_tests(native))), (0, 1))
        self.assertIn("[1, 2]", af.public_tests(native)[0]["message"])
        self.assertIn("[1, 3]", af.public_tests(native)[0]["message"])
        self.assertNotIn("PRIVATE_ARRAY_MESSAGE", json.dumps(native))

    def test_primitive_array_and_numeric_overloads_preserve_arguments_and_groups(self) -> None:
        # Удаление любой перегрузки теряет наблюдение при неизменном результате JUnit.
        arrays = [
            ("byte", "1,2", "1,3", "[01, 02]", "[01, 03]"),
            ("short", "1,2", "1,3", "[1, 2]", "[1, 3]"),
            ("int", "1,2", "1,3", "[1, 2]", "[1, 3]"),
            ("long", "1,2", "1,3", "[1, 2]", "[1, 3]"),
            ("float", "1,2", "1,3", "[1.0, 2.0]", "[1.0, 3.0]"),
            ("double", "1,2", "1,3", "[1.0, 2.0]", "[1.0, 3.0]"),
            ("char", "'a','b'", "'a','c'", "[a, b]", "[a, c]"),
            ("boolean", "true,false", "true,true", "[true, false]", "[true, true]"),
            ("Object", '"a","b"', '"a","c"', '["a", "b"]', '["a", "c"]'),
        ]
        methods: list[str] = []
        expected: dict[str, tuple[list[tuple[str, str]], str | None]] = {}

        def grouped(name: str, assertion: str, good: Sequence[str], bad: Sequence[str],
                    want: list[tuple[str, str]], delta: str | None = None) -> None:
            args = ",".join(good)
            wrong = ",".join(bad)
            methods.append(
                f'@Test @DisplayName("{name}") void {name}(){{assertAll('
                f'()->{assertion}({args}),'
                f'()->{assertion}({wrong},"PRIVATE_STRING_MESSAGE"),'
                f'()->{assertion}({wrong},()->{{messageCalls++;return "PRIVATE_SUPPLIER_MESSAGE";}}));}}'
            )
            expected[name] = (want, delta)

        for kind, left, right, want_left, want_right in arrays:
            a, b = f"new {kind}[]{{{left}}}", f"new {kind}[]{{{right}}}"
            grouped("array_" + kind, "assertArrayEquals", (a, a), (a, b),
                    [(want_left, want_left), (want_left, want_right), (want_left, want_right)])
        for kind, left, right, want_left, want_right in [
            ("byte", "(byte)1", "(byte)2", "1", "2"),
            ("short", "(short)1", "(short)2", "1", "2"),
            ("int", "1", "2", "1", "2"),
            ("long", "1L", "2L", "1", "2"),
            ("float", "1f", "2f", "1.0", "2.0"),
            ("double", "1d", "2d", "1.0", "2.0"),
            ("char", "'a'", "'b'", "a", "b"),
        ]:
            grouped("equals_" + kind, "assertEquals", (left, left), (left, right),
                    [(want_left, want_left), (want_left, want_right), (want_left, want_right)])
            grouped("notEquals_" + kind, "assertNotEquals", (left, right), (left, left),
                    [(want_left, want_right), (want_left, want_left), (want_left, want_left)])
        for kind, suffix in [("float", "f"), ("double", "d")]:
            a, b, delta = "1" + suffix, "2" + suffix, "0.25" + suffix
            grouped("deltaEquals_" + kind, "assertEquals", (a, a, delta), (a, b, delta),
                    [("1.0", "1.0"), ("1.0", "2.0"), ("1.0", "2.0")], "0.25")
            grouped("deltaNotEquals_" + kind, "assertNotEquals", (a, b, delta), (a, a, delta),
                    [("1.0", "2.0"), ("1.0", "1.0"), ("1.0", "1.0")], "0.25")
            a, b = f"new {kind}[]{{1,2}}", f"new {kind}[]{{1,3}}"
            grouped("deltaArray_" + kind, "assertArrayEquals", (a, a, delta), (a, b, delta),
                    [("[1.0, 2.0]", "[1.0, 2.0]"),
                     ("[1.0, 2.0]", "[1.0, 3.0]"), ("[1.0, 2.0]", "[1.0, 3.0]")], "0.25")
        self.source("".join(methods), '''int messageCalls;
          @AfterEach void messages(){if(messageCalls!=1)throw new AssertionError("extra supplier evaluation");}''')
        result = self.run_job()
        assert "score" in result
        counts = af.result_counts(result)
        self.assertEqual((counts["executed"], counts["failed"], result["score"]), (29, 29, 0))
        self.assertTrue(counts["complete"])
        for case in counts["cases"]:
            with self.subTest(case=case["name"]):
                want, delta = expected[case["name"]]
                self.assertEqual([(c["expected"], c["actual"]) for c in af.case_checks(case)], want)
                self.assertEqual([c["delegated"] for c in af.case_checks(case)], ["returned", "threw", "threw"])
                self.assertTrue(all(c["availability"] == "complete" for c in af.case_checks(case)))
                if delta is not None:
                    self.assertEqual([af.check_text(c, "delta") for c in af.case_checks(case)], [delta] * 3)
        native = feedback(result, self.cfg)
        self.assertEqual((af.public_score(native), len(af.public_tests(native))), (0, 29))
        self.assertNotIn("PRIVATE_", json.dumps(native))

    def test_lazy_throwing_message_and_opaque_array_keep_native_delegate(self) -> None:
        self.source('''
          @Test @DisplayName("Ленивый и бросающий message") void supplier(){
            int[] calls={0};
            assertArrayEquals(new long[]{1},new long[]{1},()->{calls[0]++;throw new Error("PRIVATE_EAGER");});
            assertNotEquals(1d,2d,()->{calls[0]++;throw new Error("PRIVATE_EAGER");});
            RuntimeException marker=new RuntimeException("PRIVATE_THROWING_MESSAGE");
            try {assertArrayEquals(new long[]{1},new long[]{2},()->{calls[0]++;throw marker;});
              throw new AssertionError("lost throw");}
            catch(RuntimeException actual){if(actual!=marker)throw new AssertionError("changed throw");}
            if(calls[0]!=1)throw new AssertionError("extra evaluation");
          }
          @Test @DisplayName("Непрозрачный элемент") void opaque(){
            Opaque a=new Opaque(),b=new Opaque();
            assertArrayEquals(new Object[]{a},new Object[]{b},"PRIVATE_OPAQUE_MESSAGE");
            if(equalsCalls!=1||toStringCalls!=0)throw new AssertionError("extra student method");
          }
        ''', '''static int equalsCalls,toStringCalls;
          static class Opaque {
            public boolean equals(Object value){equalsCalls++;return true;}
            public String toString(){toStringCalls++;return "PRIVATE_OPAQUE_TEXT";}
          }''')
        result = self.run_job()
        assert "score" in result
        self.assertEqual((af.result_counts(result)["executed"], af.result_counts(result)["passed"], result["score"]), (2, 2, 1))
        cases = {case["name"]: case for case in af.result_counts(result)["cases"]}
        checks = af.case_checks(cases["Ленивый и бросающий message"])
        self.assertEqual([c["delegated"] for c in checks], ["returned", "returned", "threw"])
        self.assertEqual((checks[-1]["expected"], checks[-1]["actual"]), ("[1]", "[2]"))
        self.assertIn("unsupported", af.case_checks(cases["Непрозрачный элемент"])[0]["availability"])
        native = feedback(result, self.cfg)
        self.assertEqual(af.completeness(native), "incomplete")
        self.assertNotIn("PRIVATE_", json.dumps(native))


if __name__ == "__main__":
    unittest.main()
