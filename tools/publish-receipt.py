#!/usr/bin/env python3
"""Проверенные registry digests и соответствие runtime-профилей образам."""
import copy
import json
import os
from pathlib import Path
import re

PROFILE_IMAGES={'java25-junit-v1':'java','java25-mutation-v1':'java','fish-git-v1':'fish'}
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

if __name__=='__main__':
    images={key:os.environ[key.upper()+'_DIGEST'] for key in REPOSITORIES}
    registry=assign_images(json.loads(Path('runtime-profiles.json').read_text()),images)
    Path('published-runtime-profiles.json').write_text(json.dumps(registry,indent=2)+'\n')
    receipt={'schemaVersion':2,'sourceCommit':os.environ['GITHUB_SHA'],'version':os.environ['VERSION'],'images':images,'deliverySchemaVersion':3,'resultsSchemaVersion':2,'runtimeProfilesSha256':__import__('hashlib').sha256(Path('published-runtime-profiles.json').read_bytes()).hexdigest()}
    Path('runtime-image.json').write_text(json.dumps(receipt,indent=2)+'\n')
