"""Синтетический unit registry: digests не обозначают существующие OCI images."""
import copy
import hashlib
import json
import contextlib
import importlib.util
import re
import shutil
import tempfile
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
 spec=importlib.util.spec_from_file_location('fixture_preparation',ROOT/'tools/prepare_native_toolchain.py');preparation=importlib.util.module_from_spec(spec);spec.loader.exec_module(preparation)
 fish=preparation._fish_view(ROOT)['profiles']['fish-git-v1'];fish['image']='unit.invalid/synthetic-fixture@sha256:'+'1'*64
 value['profiles']['fish-git-v1']=fish
 return value

def write_registry(directory):
 path=Path(directory)/'unit-runtime-profiles.json';path.write_text(json.dumps(registry(),indent=2)+'\n');return path

def unit_platform(case):
 if not hasattr(case,'_unit_platform_view'):case._unit_platform_view=case.enterContext(platform_tree())
 return case._unit_platform_view

def image_evidence(runtime,image):
 with platform_tree(**({'fish_image':image} if runtime=='fish-git-v1' else {'java_image':image})) as root:
  spec=importlib.util.spec_from_file_location('image_fixture_jobs',root/'tools/grading_job.py');jobs=importlib.util.module_from_spec(spec);spec.loader.exec_module(jobs)
  return jobs.runtime_evidence(runtime,json.loads((root/'runtime-profiles.json').read_text()))

@contextlib.contextmanager
def platform_tree(*,java_image=None,fish_image=None):
 """Temporary file/root fixture, never a release checkout or image admission."""
 for image in (java_image,fish_image):
  if image is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Actual fixture execution requires a built local image ID')
 value=registry();lock=None
 if java_image is not None or fish_image is not None:
  spec=importlib.util.spec_from_file_location('actual_fixture_preparation',ROOT/'tools/prepare_native_toolchain.py');preparation=importlib.util.module_from_spec(spec);spec.loader.exec_module(preparation)
  preparation.verify_context(ROOT);value={'schemaVersion':1,'profiles':{}}
  if java_image is not None:
   value=json.loads((ROOT/'.native-toolchain/runtime-profiles.json').read_text())
   for row in value['profiles'].values():row['image']=java_image
   lock=(ROOT/'.native-toolchain/operator/expected-toolchain-lock.json').read_bytes()
  if fish_image is not None:
   row=json.loads((ROOT/'.native-toolchain/fish-runtime-profiles.json').read_text())['profiles']['fish-git-v1'];row['image']=fish_image;value['profiles']['fish-git-v1']=row
 with tempfile.TemporaryDirectory(prefix='platform-test-view-') as temporary:
  root=Path(temporary);files={}
  for directory in ('runtime','schemas','tools'):
   shutil.copytree(ROOT/directory,root/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  for name in ('images/java25-grader/grade.py','images/fish-git-grader/grade.py','images.lock.json','VERSION'):
   path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
  for path in sorted(root.rglob('*')):
   if path.is_file():
    name=path.relative_to(root).as_posix();pin=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=pin:raise ValueError('Test source copy drift: '+name)
    files[name]=pin
  if lock is not None:(root/'runtime/gradle-jar-v1/toolchain-lock.json').write_bytes(lock)
  (root/'runtime-profiles.json').write_text(json.dumps(value,indent=2)+'\n')
  manifest={'scope':'source-unit-fictional-images' if java_image is None and fish_image is None else 'actual-local-image-input-no-OCI-claim','sourceCopies':files,'overrides':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('runtime-profiles.json','runtime/gradle-jar-v1/toolchain-lock.json')}}
  (root/'fixture-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  yield root
