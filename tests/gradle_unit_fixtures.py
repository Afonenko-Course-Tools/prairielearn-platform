"""Синтетический unit registry: digests не обозначают существующие OCI images."""
import copy
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def registry():
 value=json.loads((ROOT/'runtime-profiles.json').read_text())
 for name,p in value['profiles'].items():
  p['image']='unit.invalid/synthetic-fixture@sha256:'+'1'*64
  p['runnerSha256']=hashlib.sha256((ROOT/p.get('runner','images/java25-grader/grade.py')).read_bytes()).hexdigest()
  for filename in p['sharedFiles']:p['sharedFiles'][filename]=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()
 native=copy.deepcopy(value['profiles']['java25-junit-v1'])
 for filename in ('build.gradle','settings.gradle','toolchain-lock.json'):
  p='runtime/gradle-jar-v1/'+filename
  native['sharedFiles'][p]=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
 value['profiles']['java25-gradle-junit-v1']=native
 return value
