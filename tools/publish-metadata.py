#!/usr/bin/env python3
"""Сведения об OCI образах выпуска и обычная конфигурация runtime-профилей."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from json_boundary import JSONObject, json_object
from publication_types import ImageReferences, PublishedRegistry, RuntimeImage

ROOT = Path(__file__).resolve().parents[1]
PROFILE_IMAGES = {'java25-junit-v1':'java', 'java25-mutation-v1':'java',
                  'java25-gradle-junit-v1':'java', 'fish-git-v1':'fish'}
REPOSITORIES = {'java':'java25-grader', 'fish':'fish-git-grader',
                'community':'prairielearn-community-gateway', 'workspace':'sp-git-workspace'}

def assign_images(registry: object, images: ImageReferences) -> PublishedRegistry:
    if set(images) not in ({'java','fish','community'}, set(REPOSITORIES)):
        raise ValueError('Java, fish and Community image roles required')
    image_values: dict[str, str] = {}
    for name, value in images.items():
        if not isinstance(value, str) or not re.fullmatch(
                r'ghcr\.io/[a-z0-9-]+/'+REPOSITORIES[name]+r'@sha256:[a-f0-9]{64}', value):
            raise ValueError('Published OCI digest belongs to another image role')
        image_values[name] = value
    source = json_object(registry)
    raw_profiles = source.get('profiles')
    if not isinstance(raw_profiles, dict) or set(raw_profiles) != set(PROFILE_IMAGES):
        raise ValueError('Unsupported runtime profile set')
    profiles: dict[str, JSONObject] = {}
    for name, profile in raw_profiles.items():
        if not isinstance(profile, dict):
            raise ValueError('Runtime profile must be an object')
        profiles[name] = {**profile, 'image': image_values[PROFILE_IMAGES[name]]}
    workspace_images: dict[str, dict[str, str]] = {}
    if 'workspace' in images:
        workspace_images['sp-git-workspace-v1'] = {'image':images['workspace']}
    return PublishedRegistry(schemaVersion=2, profiles=profiles, workspaceImages=workspace_images)


def release_registry(root: Path, images: ImageReferences, source_commit: str, version: str) -> PublishedRegistry:
    commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True).strip()
    if source_commit != commit or version != (root/'VERSION').read_text().strip():
        raise ValueError('Release source commit/version differs from checkout')
    return assign_images(json.loads((root/'runtime-profiles.json').read_bytes()), images)


def main() -> int:
    try:
        images: ImageReferences = {'java':os.environ['JAVA_DIGEST'], 'fish':os.environ['FISH_DIGEST'],
            'community':os.environ['COMMUNITY_DIGEST']}
        if 'WORKSPACE_DIGEST' in os.environ:
            images['workspace'] = os.environ['WORKSPACE_DIGEST']
        source_commit, version = os.environ['GITHUB_SHA'], os.environ['VERSION']
        registry = release_registry(ROOT, images, source_commit, version)
        receipt: RuntimeImage = {'schemaVersion':3, 'sourceCommit':source_commit,
            'version':version, 'images':images, 'deliverySchemaVersion':5, 'resultsSchemaVersion':2}
        for name, value in (('published-runtime-profiles.json',registry), ('runtime-image.json',receipt)):
            Path(name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Publication metadata refused: '+str(error), file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
