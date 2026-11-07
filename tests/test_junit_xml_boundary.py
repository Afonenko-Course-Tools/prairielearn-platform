"""Обычная проверка формы и весов JSON-отчёта слушателя JUnit."""
import json
from pathlib import Path
import tempfile
import unittest
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime'))
import junit_result as reader

class JUnitResultTests(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tempfile.TemporaryDirectory())
        self.report = Path(self.root)/'feedback.json'
        self.value = {'complete':True,'registered':['case-1'],'started':['case-1'],
            'outcomes':{'case-1':'successful'},'containerFailures':0,'failureKinds':{},
            'cases':[{'id':'case-1','name':'обычный тест','status':'passed'}],
            'grading':{'case-1':{'weight':1,'name':'обычный тест','description':'','owner':'class-1'}},'classMaximums':{}}
    def read(self):
        self.report.write_text(json.dumps(self.value))
        return reader.read_junit_report(self.report)
    def test_completed_report(self):
        raw, counts = self.read()
        self.assertEqual((raw['score'],counts['passed']), (1,1))
    def test_class_maximum_preserves_scoring(self):
        self.value['classMaximums']={'class-1':4}
        self.assertEqual(self.read()[0]['score'],0.25)
    def test_incomplete_run_is_rejected(self):
        self.value['complete']=False
        with self.assertRaises(ValueError): self.read()
    def test_missing_case_is_rejected(self):
        self.value['cases']=[]
        with self.assertRaises(ValueError): self.read()
    def test_invalid_weight_is_rejected(self):
        for weight in (-1, True, float('inf'), float('nan')):
            with self.subTest(weight=weight):
                self.value['grading']['case-1']['weight']=weight
                with self.assertRaises(ValueError): self.read()
