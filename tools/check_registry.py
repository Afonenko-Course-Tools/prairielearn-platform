#!/usr/bin/env python3
"""Validate native-course pins before any checkout or deployment."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

class RegistryError(Exception): pass

def validate_registry(registry, images):
    if not isinstance(registry,dict) or set(registry)!={'schema','courses'} or registry['schema']!='pl-courses-v1' or not isinstance(registry['courses'],list) or not registry['courses']:
        raise RegistryError('Expected nonempty pl-courses-v1 registry')
    if not isinstance(images,dict): raise RegistryError('Missing image lock')
    pl=images.get('prairielearn',{}); grader=images.get('javaGrader',{})
    if not isinstance(pl,dict) or not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',str(pl.get('image',''))):
        raise RegistryError('PrairieLearn image requires an exact digest')
    if not isinstance(grader,dict) or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(grader.get('localImageId',''))) or not re.fullmatch(r'[^\s]+:[A-Za-z0-9][A-Za-z0-9_.-]*',str(grader.get('localImage',''))) or str(grader['localImage']).endswith(':latest'):
        raise RegistryError('Local Java grader requires a versioned image and verified image ID')
    ids=set(); mounts=set()
    for course in registry['courses']:
        if not isinstance(course,dict) or set(course)!={'id','repository','commit','mount'} or not all(isinstance(v,str) for v in course.values()):
            raise RegistryError('Every course requires explicit string fields')
        if not re.fullmatch(r'[a-z][a-z0-9-]*',course['id']) or course['id'] in ids:
            raise RegistryError('Invalid or duplicate course ID')
        if not re.fullmatch(r'[a-f0-9]{40}',course['commit']): raise RegistryError('Course requires an exact Git commit')
        if not re.fullmatch(r'/course(?:[2-9]|[1-9][0-9]+)?',course['mount']) or course['mount'] in mounts:
            raise RegistryError('Invalid or duplicate native mount')
        url=course['repository']
        try: parsed=urlsplit(url)
        except ValueError as error: raise RegistryError('Invalid repository URL') from error
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.strip('/') or re.search(r'[\s\\%]',url) or '..' in parsed.path.split('/'):
            raise RegistryError('Repository requires a credential-free HTTPS URL')
        ids.add(course['id']);mounts.add(course['mount'])
    return registry['courses']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry',type=Path);parser.add_argument('--images',type=Path,default=Path(__file__).resolve().parents[1]/'images.lock.json')
    args=parser.parse_args()
    try:
        courses=validate_registry(json.loads(args.registry.read_text()),json.loads(args.images.read_text()))
    except (RegistryError,OSError,ValueError) as error: parser.exit(1,f'Registry rejected: {error}\n')
    print(f'Validated {len(courses)} exact course pins')

if __name__=='__main__': main()
