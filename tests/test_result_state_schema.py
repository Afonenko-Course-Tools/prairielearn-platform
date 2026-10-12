import copy
import json
from pathlib import Path
import unittest
import jsonschema
ROOT=Path(__file__).resolve().parents[1]
class ResultStateSchema(unittest.TestCase):
 def test_not_started_has_zero_completed_and_null_lab_aggregate(self):
  for name in ['gateway-results','gateway-work-results']:
   schema=json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text())
   base={'schemaVersion':2,'source':'per-slot-results-v2','userUid':'u','instance':'fixture','deliveryHash':'a'*64,'workId':'lab','state':'not-started','currentAttempt':None,'slots':[],'completion':{'completedRequired':0,'requiredCount':3,'atLeast':2,'passed':False}}
   if name=='gateway-results':base.update(assignmentId='a',version=1)
   else:base.update(scoreGiven=None,scoreMaximum=None)
   jsonschema.validate(base,schema)
   for field,value in [('completedRequired',1),('passed',True)]:
    bad=copy.deepcopy(base);bad['completion'][field]=value
    with self.subTest(schema=name,field=field),self.assertRaises(jsonschema.ValidationError):jsonschema.validate(bad,schema)
   if name=='gateway-work-results':
    for field,value in [('scoreGiven',1),('scoreMaximum',3)]:
     bad={**base,field:value}
     with self.subTest(field=field),self.assertRaises(jsonschema.ValidationError):jsonschema.validate(bad,schema)
