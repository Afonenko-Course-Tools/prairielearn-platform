"""Временное дерево публичного runtime без собственных inventories."""
import contextlib
import json
import shutil
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def registry():
    value=json.loads((ROOT/'runtime-profiles.json').read_text())
    for profile in value['profiles'].values():
        profile['image']='unit.invalid/synthetic-fixture@sha256:'+'1'*64
    return value

def write_registry(directory):
    path=Path(directory)/'unit-runtime-profiles.json'
    path.write_text(json.dumps(registry()))
    return path

def unit_platform(case):
    if not hasattr(case,'_unit_platform_view'):
        case._unit_platform_view=case.enterContext(platform_tree())
    return case._unit_platform_view

@contextlib.contextmanager
def platform_tree(*,java_image=None,fish_image=None):
    value=registry()
    for name,profile in value['profiles'].items():
        image=fish_image if name=='fish-git-v1' else java_image
        if image is not None:profile['image']=image
    with tempfile.TemporaryDirectory(prefix='platform-test-view-') as temporary:
        root=Path(temporary)
        for directory in ('runtime','schemas','tools'):
            shutil.copytree(ROOT/directory,root/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ('images/java25-grader/grade.py','images/fish-git-grader/grade.py','images.lock.json','VERSION'):
            path=root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((ROOT/name).read_bytes())
        (root/'runtime-profiles.json').write_text(json.dumps(value))
        yield root
