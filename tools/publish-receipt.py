#!/usr/bin/env python3
"""Сведения об OCI образах выпуска и обычная конфигурация runtime-профилей."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import NotRequired, TypedDict

ROOT = Path(__file__).resolve().parents[1]
PROFILE_IMAGES = {'java25-junit-v1':'java', 'java25-mutation-v1':'java',
                  'java25-gradle-junit-v1':'java', 'fish-git-v1':'fish'}
REPOSITORIES = {'java':'java25-grader', 'fish':'fish-git-grader',
                'community':'prairielearn-community-gateway', 'workspace':'sp-git-workspace'}

class ImageReferences(TypedDict):
    java: str
    fish: str
    community: str
    workspace: NotRequired[str]

class RuntimeImage(TypedDict):
    schemaVersion: int
    sourceCommit: str
    version: str
    images: ImageReferences
    deliverySchemaVersion: int
    resultsSchemaVersion: int


def assign_images(registry, images: ImageReferences):
    if set(images) not in ({'java','fish','community'}, set(REPOSITORIES)):
        raise ValueError('Java, fish and Community image roles required')
    for name, value in images.items():
        if not isinstance(value, str) or not re.fullmatch(
                r'ghcr\.io/[a-z0-9-]+/'+REPOSITORIES[name]+r'@sha256:[a-f0-9]{64}', value):
            raise ValueError('Published OCI digest belongs to another image role')
    result = copy.deepcopy(registry)
    if set(result['profiles']) != set(PROFILE_IMAGES):
        raise ValueError('Unsupported runtime profile set')
    for name, profile in result['profiles'].items():
        profile['image'] = images[PROFILE_IMAGES[name]]
    result['schemaVersion'] = 2
    result['workspaceImages'] = {}
    if 'workspace' in images:
        result['workspaceImages']['sp-git-workspace-v1'] = {'image':images['workspace']}
    return result


def release_registry(root: Path, images: ImageReferences, source_commit: str, version: str):
    commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True).strip()
    if source_commit != commit or version != (root/'VERSION').read_text().strip():
        raise ValueError('Release source commit/version differs from checkout')
    return assign_images(json.loads((root/'runtime-profiles.json').read_bytes()), images)


def main():
    try:
        images: ImageReferences = {'java':os.environ['JAVA_DIGEST'], 'fish':os.environ['FISH_DIGEST'],
            'community':os.environ['COMMUNITY_DIGEST']}
        if 'WORKSPACE_DIGEST' in os.environ:
            images['workspace'] = os.environ['WORKSPACE_DIGEST']
        source_commit, version = os.environ['GITHUB_SHA'], os.environ['VERSION']
        registry = release_registry(ROOT, images, source_commit, version)
        receipt: RuntimeImage = {'schemaVersion':3, 'sourceCommit':source_commit,
            'version':version, 'images':images, 'deliverySchemaVersion':4, 'resultsSchemaVersion':2}
        for name, value in (('published-runtime-profiles.json',registry), ('runtime-image.json',receipt)):
            Path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Publication metadata refused: '+str(error), file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
