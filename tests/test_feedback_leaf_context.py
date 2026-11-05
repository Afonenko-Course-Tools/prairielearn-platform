"""Публичные данные и LF остаются в фактических native leaf-карточках."""
import json
import unittest
from test_student_feedback import feedback


def result(leaves=(('a', 'Answer#run'),)):
    ids = [id for id, _ in leaves]
    return {
        'classification': 'success', 'score': 1,
        'counts': {
            'complete': True, 'eventErrors': 0, 'feedbackProtocolVersion': 2,
            'discovered': len(ids), 'executed': len(ids), 'passed': len(ids),
            'failed': 0, 'skipped': 0, 'aborted': 0, 'containerFailures': 0,
            'registered': ids, 'started': ids,
            'outcomes': {id: 'successful' for id in ids}, 'failureKinds': {},
            'cases': [{'id': id, 'name': 'Значение сохранено '+id,
                       'test': test, 'status': 'passed', 'checks': []}
                      for id, test in leaves],
        },
    }


class LeafContext(unittest.TestCase):
    def test_leaf_keeps_ordinary_display_name_and_one_score(self):
        source = result()
        source['rawResult'] = {'output': 'PRIVATE_CANARY'}
        native = feedback.student_result(source, {})
        self.assertEqual(len(native['tests']), 1)
        card = native['tests'][0]
        self.assertEqual((card['points'], card['max_points'], native['score']), (1, 1, 1))
        self.assertEqual(card['name'], source['counts']['cases'][0]['name'])
        self.assertNotIn('PRIVATE_CANARY', json.dumps(native))
        self.assertNotIn('Answer#run', json.dumps(native))
        self.assertNotIn('publicCases', native['feedback'])

    def test_two_junit_leaves_with_one_method_remain_two_actual_leaves(self):
        native = feedback.student_result(result((('a', 'Answer#run'), ('b', 'Answer#run'))), {})
        self.assertEqual(len(native['tests']), 2)
        self.assertEqual(len(native['feedback']['cases']), 2)
        self.assertTrue(all(card['points'] == 1 for card in native['tests']))

    def test_tool_failure_does_not_expose_leaf_values_or_student_score(self):
        source = result(); source['classification'] = 'infrastructure-failure'
        source['counts']['cases'][0]['expected'] = 'PRIVATE_EXPECTED'
        native = feedback.student_result(source, {})
        self.assertFalse(native['gradable'])
        self.assertNotIn('score', native)
        self.assertFalse(native.get('tests'))
        self.assertNotIn('PRIVATE_EXPECTED', json.dumps(native))

    def test_compile_admission_does_not_invent_failed_dependent_tests(self):
        native = feedback.student_result({'classification': 'student-compilation-failure',
                                         'gradable': True, 'score': 0}, {})
        self.assertEqual(native['score'], 0)
        self.assertFalse(native.get('tests'))

    def test_executed_leaf_retains_assertion_observation(self):
        source = result()
        source['counts']['cases'][0]['checks'] = [{
            'site': 'AnswerTest.java:12:1', 'property': 'равенство',
            'availability': 'complete', 'delegated': 'returned',
            'expected': '12', 'actual': '12',
        }]
        native = feedback.student_result(source, {})
        self.assertIn('Получено: 12', native['tests'][0]['message'])
        self.assertIn('Ожидается: 12', native['tests'][0]['message'])

    def test_assertion_details_and_newlines_use_preformatted_native_message(self):
        source = result()
        source['counts']['cases'][0]['checks'] = [{
            'site': 'AnswerTest.java:12:1', 'property': 'равенство с допуском',
            'availability': 'complete', 'delegated': 'returned',
            'expected': 'a\nb', 'actual': 'a\nb', 'delta': '0.01',
            'differenceIndex': '3', 'differenceLine': '2', 'differenceColumn': '1',
            'differenceExpected': 'b', 'differenceActual': 'c',
        }]
        native = feedback.student_result(source, {})
        message = native['tests'][0]['message']
        for detail in ('Ожидается: a\nb', 'Допуск: 0.01', 'Первое различие: 3', 'Строка: 2', 'Полученный фрагмент: c'):
            self.assertIn(detail, message)


if __name__ == '__main__':
    unittest.main()
