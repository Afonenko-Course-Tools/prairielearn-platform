#!/usr/bin/env python3
"""Stage exact native delivery commits and emit a read-only Compose mount override."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TOOLS=Path(__file__).resolve().parent
sys.path.insert(0,str(TOOLS))
from check_registry import RegistryError, validate_registry
spec=importlib.util.spec_from_file_location('native_builder',TOOLS/'build-course.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class StorageError(Exception):pass

def git(directory,*args):
    try:
        result=subprocess.run(['git','-c','core.hooksPath=/dev/null',*args],cwd=directory,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'},capture_output=True,text=True,check=True,timeout=120)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
        raise StorageError(f'Exact native Git checkout failed: {directory.name}') from error
    return result.stdout.strip()

def validate_checkout(path,course):
    if path.is_symlink() or not path.is_dir() or git(path,'rev-parse','HEAD')!=course['commit'] or git(path,'remote','get-url','origin')!=course['repository'] or git(path,'status','--porcelain','--untracked-files=all'):
        raise StorageError('Existing checkout does not match its clean exact pin')
    try:
        info=builder.read_json(path/'infoCourse.json'); provenance=builder.read_json(path/'provenance.json')
        if not isinstance(info.get('name'),str) or provenance.get('schema')!='pl-provenance-v1' or not isinstance(provenance.get('files'),dict) or not provenance['files']:
            raise StorageError('Native delivery requires course metadata and content provenance')
        for key in ('source','builder'):
            record=provenance.get(key)
            if not isinstance(record,dict) or record.get('dirty') is not False:
                raise StorageError('Accepted native deliveries require clean source and builder commits')
        actual=set()
        for root,dirs,files in os.walk(path):
            relative=Path(root).relative_to(path)
            if relative==Path('.'):
                dirs[:]=[d for d in dirs if d!='.git']
            for name in dirs+files:
                if (Path(root)/name).is_symlink():raise StorageError('Native payload symlinks are forbidden')
            for name in files:
                p=Path(root)/name
                if not p.is_file():raise StorageError('Native payload special files are forbidden')
                actual.add(p.relative_to(path).as_posix())
        for name,digest in provenance['files'].items():
            p=builder.relative_path(path,name)
            if not isinstance(digest,str) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
                raise StorageError('Native payload does not match its provenance hashes')
        allowed=set(provenance['files'])|{'provenance.json','README.md','LICENSE','AGENTS.md','.gitignore'}
        if actual-allowed:raise StorageError('Native checkout contains unrecorded payload files')
    except (builder.BuildError,OSError,ValueError) as error:
        raise StorageError('Invalid native delivery or provenance') from error

def stage_course(course,storage):
    try:
        images=builder.read_json(TOOLS.parent/'images.lock.json')
        validate_registry({'schema':'pl-courses-v1','courses':[course]},images)
        storage=Path(storage).absolute()
        if not storage.is_dir() or storage.resolve()!=storage or storage.is_symlink():
            raise StorageError('Storage must be an existing absolute real directory')
        parent=storage/course['id']
        if parent.is_symlink():raise StorageError('Storage course parent must not be a symlink')
        parent.mkdir(exist_ok=True)
        destination=parent/course['commit']
        if destination.exists() or destination.is_symlink():
            validate_checkout(destination,course);return destination
        with tempfile.TemporaryDirectory(prefix='.stage-',dir=parent) as temporary:
            stage=Path(temporary)/'native'
            # The registry URL is validated before invoking Git. Checkout is by
            # object identity, with hooks disabled; no moving branch is trusted.
            git(parent,'clone','--no-checkout','--',course['repository'],str(stage))
            git(stage,'checkout','--detach',course['commit'])
            validate_checkout(stage,course)
            builder.publish_directory(stage,destination)
        return destination
    except (RegistryError,builder.BuildError,OSError) as error:
        raise StorageError(str(error)) from error

def stage_registry(registry,images,storage):
    courses=validate_registry(registry,images)
    volumes=[]
    for course in courses:
        path=stage_course(course,storage)
        volumes.append({'type':'bind','source':str(path),'target':course['mount'],'read_only':True,'bind':{'create_host_path':False}})
    return {'services':{'pl':{'volumes':volumes}}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry',type=Path);parser.add_argument('--storage',required=True,type=Path);parser.add_argument('--compose-output',required=True,type=Path)
    parser.add_argument('--images',type=Path,default=TOOLS.parent/'images.lock.json');args=parser.parse_args()
    try:
        registry=builder.read_json(args.registry);images=builder.read_json(args.images)
        override=stage_registry(registry,images,args.storage)
        data=json.dumps(override,indent=2)+'\n'
        if args.compose_output.exists():
            if args.compose_output.read_text()!=data:raise StorageError('Compose output exists with different contents; choose a fresh output')
        else:
            with args.compose_output.open('x') as f:f.write(data)
    except (StorageError,RegistryError,builder.BuildError,OSError) as error:parser.exit(1,f'Course staging rejected: {error}\n')
    print(f'Staged {len(registry["courses"])} exact native deliveries; PL sync remains required')

if __name__=='__main__':main()
