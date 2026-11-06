"""Повреждённая выдача JUnit остаётся инфраструктурным результатом."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('xml_result',ROOT/'runtime/junit_result.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)

class JUnitXmlBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.xml=self.root/'TEST-fixture.xml'
        self.xml.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase name="ok"><system-out>unique-id: case-1\ndisplay-name: ok</system-out></testcase></testsuite>')
        self.feedback=self.root/'feedback.json'
        self.value={'complete':True,'verifiedOutcomes':{'case-1':'successful'},'feedbackProtocolVersion':2,'containerFailures':0,'failureKinds':{},'cases':[{'id':'case-1','name':'ok','status':'passed','checks':[]}],'grading':{'case-1':{'weight':1,'name':'ok','description':'','owner':'class-1'}},'classMaximums':{}}

    def run_reader(self):
        self.feedback.write_text(json.dumps(self.value))
        return reader.read_junit_xml(self.root,self.feedback)

    def test_generated_report_is_read(self):
        self.assertEqual(self.run_reader()[0]['score'],1)

    def test_class_maximum_without_direct_leaf_is_preserved(self):
        self.value['classMaximums']={'outer-class':3}
        raw,counts=self.run_reader()
        self.assertEqual(raw['max_points'],4)
        self.assertEqual(raw['score'],0.25)
        self.assertEqual(counts['passed'],1)

    def test_successful_nonleaf_row_requires_reported_container(self):
        self.xml.write_text(self.xml.read_text().replace('tests="1"','tests="2"').replace('</testsuite>', '<testcase name="empty"><system-out>unique-id: container-1</system-out></testcase></testsuite>'))
        with self.assertRaises(ValueError):
            self.run_reader()
        self.value['successfulContainers']=['container-1']
        raw,counts=self.run_reader()
        self.assertEqual(raw['score'],1)
        self.assertEqual(counts['executed'],1)

    def test_finite_weights_cannot_overflow_aggregate_points(self):
        self.xml.write_text('<testsuite tests="2" failures="0" errors="0" skipped="0">' +
            ''.join('<testcase name="ok"><system-out>unique-id: '+uid+'</system-out></testcase>' for uid in ('case-1','case-2')) + '</testsuite>')
        self.value['verifiedOutcomes']['case-2']='successful'
        self.value['cases'].append({'id':'case-2','name':'ok','status':'passed','checks':[]})
        self.value['grading']={uid:{'weight':1e308,'name':'ok','description':'','owner':'class-1'} for uid in ('case-1','case-2')}
        with self.assertRaises(ValueError):
            self.run_reader()

    def test_finite_class_maximums_cannot_overflow_total(self):
        self.value['classMaximums']={'class-1':1e308, 'other-class':1e308}
        with self.assertRaises(ValueError):
            self.run_reader()

    def test_malformed_feedback_is_a_parse_error(self):
        for value in ([], {'complete':True}, {**self.value,'grading':{'case-1':{'weight':'bad'}}}):
            with self.subTest(value=value):
                self.value=value
                with self.assertRaises(ValueError): self.run_reader()

    def test_suite_aggregate_cannot_disagree_with_cases(self):
        valid=self.xml.read_text()
        for name in ('failures','errors','skipped'):
            with self.subTest(counter=name):
                self.xml.write_text(valid.replace(name+'="0"',name+'="1"'))
                with self.assertRaises(ValueError): self.run_reader()

    def test_nonfinite_or_boolean_weights_are_not_grading_metadata(self):
        for weight in (float('nan'),float('inf'),True,-1,'1'):
            with self.subTest(weight=weight):
                self.value['grading']['case-1']['weight']=weight
                with self.assertRaises(ValueError): self.run_reader()
