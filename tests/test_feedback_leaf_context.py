"""Публичные данные и LF остаются в фактических native leaf-карточках."""
import copy
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


DESCRIPTOR = {'publicCases': [{
    'id': 'public', 'test': 'Answer#run', 'name': 'Изменение состояния',
    'input': '2\n3', 'state': 'счётчик 7', 'action': 'прибавить', 'expected': '12',
}]}


class LeafContext(unittest.TestCase):
    def test_unique_leaf_retains_every_public_field_without_an_extra_score(self):
        source = result()
        source['publicCaseObservations'] = [{'id': 'public', 'test': 'Answer#run',
                                             'status': 'passed', 'actual': '12'}]
        source['rawResult'] = {'output': 'PRIVATE_CANARY'}
        native = feedback.student_result(source, DESCRIPTOR)
        self.assertEqual(len(native['tests']), 1)
        card = native['tests'][0]
        self.assertEqual((card['points'], card['max_points'], native['score']), (1, 1, 1))
        for value in ('Изменение состояния', 'Вход: 2\n3', 'счётчик 7', 'прибавить', 'Ожидается: 12', 'Получено: 12'):
            self.assertIn(value, card['message'])
        self.assertNotIn('PRIVATE_CANARY', json.dumps(native))
        self.assertNotIn('Answer#run', json.dumps(native))

    def test_ambiguous_method_source_is_unknown_and_adds_no_scored_leaf(self):
        native = feedback.student_result(result((('a', 'Answer#run'), ('b', 'Answer#run'))), DESCRIPTOR)
        public = native['feedback']['publicCases'][0]
        self.assertEqual(public['status'], 'unknown')
        self.assertIn('нескольким', public['statusReason'])
        self.assertEqual(len(native['tests']), 2)
        self.assertIn('Изменение состояния', native['message'])
        self.assertIn('не установлен', native['message'])

    def test_absent_selector_is_not_run_with_reason(self):
        native = feedback.student_result(result((('a', 'Answer#other'),)), DESCRIPTOR)
        public = native['feedback']['publicCases'][0]
        self.assertEqual(public['status'], 'not-run')
        self.assertTrue(public['statusReason'])
        self.assertIn('не запускался', native['message'])
        self.assertEqual(len(native['tests']), 1)

    def test_tool_failure_is_unknown_without_a_student_score(self):
        source = result(); source['classification'] = 'infrastructure-failure'
        native = feedback.student_result(source, DESCRIPTOR)
        self.assertEqual(native['feedback']['publicCases'][0]['status'], 'unknown')
        self.assertFalse(native['gradable'])
        self.assertNotIn('score', native)
        self.assertFalse(native.get('tests'))
        self.assertIn('Изменение состояния', native['message'])
        for card in native.get('tests', []):
            self.assertNotIn('points', card)
            self.assertNotIn('max_points', card)

    def test_compile_admission_does_not_invent_failed_dependent_tests(self):
        native = feedback.student_result({'classification': 'student-compilation-failure',
                                         'gradable': True, 'score': 0}, DESCRIPTOR)
        self.assertEqual(native['feedback']['publicCases'][0]['status'], 'not-run')
        self.assertEqual(native['score'], 0)
        self.assertFalse(native.get('tests'))
        self.assertIn('Вход: 2\n3', native['message'])
        self.assertIn('не запускался', native['message'])
        for card in native.get('tests', []):
            self.assertNotIn('points', card)
            self.assertNotIn('max_points', card)

    def test_explanatory_prose_wraps_without_rewriting_public_values(self):
        descriptor = copy.deepcopy(DESCRIPTOR)
        descriptor['publicCases'][0]['expected'] = 'X' * 400 + '\nвторая строка'
        native = feedback.student_result({'classification': 'student-compilation-failure',
                                         'gradable': True, 'score': 0}, descriptor)
        self.assertIn('Ожидается: ' + 'X' * 400 + '\nвторая строка', native['message'])
        explanation = native['message'].split('\n\nЧто проверяется:', 1)[0]
        self.assertTrue(all(len(line) <= 60 for line in explanation.splitlines()))

    def test_executed_leaf_does_not_deny_its_assertion_observation(self):
        source = result()
        source['counts']['cases'][0]['checks'] = [{
            'site': 'AnswerTest.java:12:1', 'property': 'равенство',
            'availability': 'complete', 'delegated': 'returned',
            'expected': '12', 'actual': '12',
        }]
        native = feedback.student_result(source, DESCRIPTOR)
        self.assertIsNone(native['feedback']['publicCases'][0]['actual'])
        self.assertNotIn('Получено: не получено', native['tests'][0]['message'])
        self.assertIn('Получено: 12', native['tests'][0]['message'])

    def test_protocol_two_unbound_observation_does_not_borrow_another_outcome(self):
        source = result()
        source['counts']['cases'][0].pop('test')
        source['publicCaseObservations'] = [{'id': 'public', 'test': 'Answer#run', 'status': 'passed', 'actual': 'UNBOUND_ACTUAL'}]
        native = feedback.student_result(source, DESCRIPTOR)
        public = native['feedback']['publicCases'][0]
        self.assertEqual((public['status'], public['actual']), ('unknown', None))
        self.assertNotIn('UNBOUND_ACTUAL', json.dumps(native))

    def test_partial_bindings_cannot_prove_an_absent_public_case_did_not_run(self):
        source = result((('a', 'Answer#other'), ('b', 'Answer#other')))
        source['counts']['cases'][1].pop('test')
        native = feedback.student_result(source, DESCRIPTOR)
        public = native['feedback']['publicCases'][0]
        self.assertEqual((public['status'], public['actual']), ('unknown', None))
        self.assertTrue(public['statusReason'])

    def test_partial_bindings_cannot_prove_a_public_match_is_unique(self):
        source = result((('a', 'Answer#run'), ('b', 'Answer#run')))
        source['counts']['cases'][1].pop('test')
        source['publicCaseObservations'] = [{'id': 'public', 'test': 'Answer#run', 'status': 'passed', 'actual': 'UNBOUND_AMBIGUOUS'}]
        native = feedback.student_result(source, DESCRIPTOR)
        public = native['feedback']['publicCases'][0]
        self.assertEqual((public['status'], public['actual']), ('unknown', None))
        self.assertNotIn('UNBOUND_AMBIGUOUS', json.dumps(native))
        self.assertTrue(all('publicCases' not in case for case in native['feedback']['cases']))

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
