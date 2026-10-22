#!/usr/bin/env python3
"""Stage exact native delivery commits and emit a read-only Compose mount override."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TOOLS=Path(__file__).resolve().parent
sys.path.insert(0,str(TOOLS))
from check_registry import RegistryError, validate_registry, INSTITUTIONS
from grading_job import validate as validate_contract, digest as contract_digest, JobError, validate_release_receipt, load_runtime_registry
spec=importlib.util.spec_from_file_location('native_builder',TOOLS/'build-course.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class StorageError(Exception):pass

def git(directory,*args):
    try:
        result=subprocess.run(['git','-c','core.hooksPath=/dev/null',*args],cwd=directory,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'},capture_output=True,text=True,check=True,timeout=120)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as error:
        raise StorageError(f'Exact native Git checkout failed: {directory.name}') from error
    return result.stdout.strip()

def validate_checkout(path,course,assembly=None):
    metadata=path/'.git'
    if metadata.is_symlink() or not metadata.is_dir():
        raise StorageError('Native checkout requires a contained real Git directory')
    if path.is_symlink() or not path.is_dir() or git(path,'rev-parse','HEAD')!=course['commit'] or git(path,'remote','get-url','origin')!=course['repository'] or git(path,'status','--porcelain','--untracked-files=all'):
        raise StorageError('Existing checkout does not match its clean exact pin')
    try:
        info=builder.read_json(path/'infoCourse.json'); provenance=builder.read_json(path/'provenance.json')
        if not isinstance(info.get('name'),str) or provenance.get('schema') not in ('pl-provenance-v1','pl-provenance-v2') or not isinstance(provenance.get('files'),dict) or not provenance['files']:
            raise StorageError('Native delivery requires course metadata and content provenance')
        if assembly:assembly.recheck()
        if provenance['schema']=='pl-provenance-v1':
            if assembly:raise StorageError('Release assembly requires v2 provenance')
            for key in ('source','builder'):
                record=provenance.get(key)
                if not isinstance(record,dict) or record.get('dirty') is not False or not isinstance(record.get('commit'),str) or not re.fullmatch(r'[a-f0-9]{40}',record['commit']):
                    raise StorageError('Accepted native deliveries require clean source and builder commits')
        elif assembly is None:raise StorageError('v2 requires trusted external release assets')
        delivery=builder.read_json(path/'delivery.json');receipt=builder.read_json(path/'verification-receipt.json')
        if provenance['schema']=='pl-provenance-v2':builder._assembly.validate_provenance(provenance,delivery,assembly)
        validate_release_receipt(receipt,delivery,path,assembly.registry if assembly else load_runtime_registry())
        for field in ('deliveryHash','sourceSnapshotHash','inventoryHash'):
            if receipt.get(field)!=delivery.get(field) or receipt.get(field)!=provenance.get(field):raise StorageError('Receipt does not match exact delivery/source/inventory')
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
        if assembly:
            validate_pinned_native(path,course)
            assembly.recheck()
            validate_pinned_native(path,course)
    except (builder.BuildError,JobError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        raise StorageError('Invalid native delivery or provenance') from error

def validate_pinned_native(path,course):
    if path.is_symlink() or not path.is_dir() or path.resolve()!=path:raise StorageError('Native checkout root must be an absolute real directory')
    metadata=path/'.git'
    if metadata.is_symlink() or not metadata.is_dir():raise StorageError('Native checkout requires a contained real Git directory')
    # V2 qualification/provenance is authority only inside this exact native Git payload.
    actual=set()
    for root,dirs,files in os.walk(path):
        if Path(root)==path:dirs[:]=[d for d in dirs if d!='.git']
        for name in dirs+files:
            p=Path(root)/name
            if p.is_symlink() or not (p.is_file() or p.is_dir()):raise StorageError('Unsafe native member')
        actual.update((Path(root)/n).relative_to(path).as_posix() for n in files)
    pinned=set()
    for item in git(path,'ls-tree','-rz','--full-tree',course['commit']).split('\0'):
        if not item:continue
        meta,name=item.split('\t',1);mode,kind,oid=meta.split()
        if kind!='blob' or mode not in ('100644','100755'):raise StorageError('Native Git type is not regular')
        p=builder.relative_path(path,name)
        if not p.is_file() or (p.stat().st_mode&0o7777)!=int(mode[-3:],8) or p.read_bytes()!=subprocess.check_output(['git','-c','core.hooksPath=/dev/null','cat-file','blob',oid],cwd=path):raise StorageError('Native payload differs from pinned Git bytes/modes')
        pinned.add(name)
    if actual!=pinned:raise StorageError('Native payload set differs from pinned Git')
    if git(path,'status','--porcelain','--untracked-files=all') or git(path,'rev-parse','HEAD')!=course['commit']:raise StorageError('Native checkout changed during validation')

def stage_course(course,storage,institutions=None,images=None,assembly=None):
    try:
        if images is None:
            images=builder.read_json(builder.PLATFORM/'images.lock.json')
            assembly=builder._assembly.for_stage(builder.PLATFORM,images)
        if 'releaseAssembly' in images and assembly is None:raise StorageError('Verified external image context required')
        if assembly:assembly.recheck()
        version='pl-courses-v2' if 'institution' in course else 'pl-courses-v1'
        validate_registry({'schema':version,'courses':[course]},images,institutions)
        storage=Path(storage).absolute()
        if not storage.is_dir() or storage.resolve()!=storage or storage.is_symlink():
            raise StorageError('Storage must be an existing absolute real directory')
        parent=storage/course['id']
        if parent.is_symlink():raise StorageError('Storage course parent must not be a symlink')
        parent.mkdir(exist_ok=True)
        destination=parent/course['commit']
        if destination.exists() or destination.is_symlink():
            validate_checkout(destination,course,assembly);return destination
        with tempfile.TemporaryDirectory(prefix='.stage-',dir=parent) as temporary:
            stage=Path(temporary)/'native'
            # The registry URL is validated before invoking Git. Checkout is by
            # object identity, with hooks disabled; no moving branch is trusted.
            git(parent,'clone','--no-checkout','--',course['repository'],str(stage))
            git(stage,'checkout','--detach',course['commit'])
            validate_checkout(stage,course,assembly)
            if assembly:
                assembly.recheck()
                validate_pinned_native(stage,course)
            builder.publish_directory(stage,destination)
        return destination
    except (RegistryError,builder.BuildError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        raise StorageError(str(error)) from error

def stage_registry(registry,images,storage,institutions=None,images_path=None):
    try:assembly=builder._assembly.for_stage(builder.PLATFORM,images,images_path)
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as error:raise StorageError('External release assets rejected') from error
    if assembly:images=assembly.images
    courses=validate_registry(registry,images,institutions)
    volumes=[]
    for course in courses:
        path=stage_course(course,storage,institutions,images,assembly)
        volumes.append({'type':'bind','source':str(path),'target':course['mount'],'read_only':True,'bind':{'create_host_path':False}})
    if assembly:
        try:assembly.recheck()
        except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError) as error:raise StorageError('Release assets changed during staging') from error
    return {'services':{'pl':{'volumes':volumes}}}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry',type=Path);parser.add_argument('--storage',required=True,type=Path);parser.add_argument('--compose-output',required=True,type=Path)
    parser.add_argument('--images',type=Path,default=TOOLS.parent/'images.lock.json')
    parser.add_argument('--institutions',type=Path,default=INSTITUTIONS);args=parser.parse_args()
    try:
        registry=builder.read_json(args.registry);images=builder.read_json(args.images)
        catalog=builder.read_json(args.institutions) if isinstance(registry,dict) and registry.get('schema')=='pl-courses-v2' else None
        override=stage_registry(registry,images,args.storage,catalog,images_path=args.images)
        data=json.dumps(override,indent=2)+'\n'
        if args.compose_output.exists():
            if args.compose_output.read_text()!=data:raise StorageError('Compose output exists with different contents; choose a fresh output')
        else:
            with args.compose_output.open('x') as f:f.write(data)
    except (StorageError,RegistryError,builder.BuildError,OSError) as error:parser.exit(1,f'Course staging rejected: {error}\n')
    print(f'Staged {len(registry["courses"])} exact native deliveries; PL sync remains required')

if __name__=='__main__':main()
