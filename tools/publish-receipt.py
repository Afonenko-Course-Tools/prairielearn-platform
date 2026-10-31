#!/usr/bin/env python3
"""Проверенные registry digests и соответствие runtime-профилей образам."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

_spec=importlib.util.spec_from_file_location('publication_preparation',Path(__file__).with_name('prepare_native_toolchain.py'))
preparation=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preparation)

ROOT=Path(__file__).resolve().parents[1]
PROFILE_IMAGES={'java25-junit-v1':'java','java25-mutation-v1':'java','java25-gradle-junit-v1':'java','fish-git-v1':'fish'}
REPOSITORIES={'java':'java25-grader','fish':'fish-git-grader','community':'prairielearn-community-gateway'}

def assign_images(registry,images):
    if set(images)!=set(REPOSITORIES):raise ValueError('Required Java, fish and Community image digests')
    for name,value in images.items():
        if not isinstance(value,str) or not re.fullmatch(r'ghcr\.io/[a-z0-9-]+/'+REPOSITORIES[name]+r'@sha256:[a-f0-9]{64}',value):raise ValueError('Digest belongs to another image or is not immutable')
    result=copy.deepcopy(registry)
    for name,profile in result['profiles'].items():
        if name not in PROFILE_IMAGES:raise ValueError('Runtime profile has no reviewed image mapping')
        profile['image']=images[PROFILE_IMAGES[name]]
    return result

def derive_release_registry(root,images,read=None,delivery_version=3):
    """Одна чистая derivation для publisher и reader pinned Git metadata."""
    read=read or preparation.read_regular
    historical=json.loads(read(root/'runtime-profiles.json'))
    preparation.require(set(historical['profiles'])=={'java25-junit-v1','java25-mutation-v1','fish-git-v1'},'Unexpected historical profile set')
    expected,_=preparation.generated_locks(json.loads(read(root/'runtime/gradle-jar-v1/toolchain-lock.json')))
    registry=preparation.baked_view(root,expected,read)
    registry['profiles']['fish-git-v1']=preparation._fish_view(root,read)['profiles']['fish-git-v1']
    workspace=images.get('workspace')
    if delivery_version==3 and workspace is not None:raise ValueError('Legacy3 cannot carry Workspace image role')
    if delivery_version not in (3,4) or set(images) not in (set(REPOSITORIES),set(REPOSITORIES)|{'workspace'}):raise ValueError('Closed release image roles required')
    result=assign_images(registry,{k:v for k,v in images.items() if k!='workspace'})
    if delivery_version==4:
        result['schemaVersion']=2;result['workspaceImages']={}
        if workspace is not None:
            if not isinstance(workspace,str) or not re.fullmatch(r'ghcr\.io/[a-z0-9-]+/sp-git-workspace@sha256:[a-f0-9]{64}',workspace):raise ValueError('Exact qualified Workspace image role required')
            result['workspaceImages']['sp-git-workspace-v1']={'image':workspace}
    return result,expected

def release_registry(root,images,source_commit,version):
    # Publisher сохраняет прежние authenticated preparation/clean-source guards.
    manifest=preparation.verify_context(root)
    preparation.require(manifest['source']['commit']==source_commit,'Published source must equal prepared clean HEAD')
    preparation.require(manifest['version']==version,'Published version must equal prepared VERSION')
    registry,lock=derive_release_registry(root,images,delivery_version=4)
    preparation.require(preparation.verify_context(root)==manifest,'Prepared inputs changed during publication metadata generation')
    return registry,lock

def main():
    try:
        images={key:os.environ[key.upper()+'_DIGEST'] for key in REPOSITORIES}
        if 'WORKSPACE_DIGEST' in os.environ:images['workspace']=os.environ['WORKSPACE_DIGEST']
        registry,lock=release_registry(ROOT,images,os.environ['GITHUB_SHA'],os.environ['VERSION'])
        data=preparation.encode(registry)
        receipt={'schemaVersion':3,'sourceCommit':os.environ['GITHUB_SHA'],'version':os.environ['VERSION'],'images':images,'deliverySchemaVersion':4,'resultsSchemaVersion':2,'runtimeProfilesSha256':preparation.digest_bytes(data)}
        # Release assembly supplies this generated lock at the existing runtime
        # path. The canonical prepared-status source lock remains unchanged.
        Path('published-runtime-profiles.json').write_bytes(data)
        Path('published-toolchain-lock.json').write_bytes(lock)
        Path('runtime-image.json').write_bytes(preparation.encode(receipt))
        return 0
    except (ValueError,OSError,KeyError) as error:
        print('Publication metadata refused: '+str(error),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
