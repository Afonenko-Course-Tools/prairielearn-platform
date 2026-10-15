#!/usr/bin/env python3
"""Validate native-course pins before any checkout or deployment."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

class RegistryError(Exception): pass

INSTITUTIONS=Path(__file__).resolve().parents[1]/'config/institutions.json'

def validate_institutions(catalog):
    if not isinstance(catalog,dict) or set(catalog)!={'schema','institutions'} or catalog['schema']!='pl-institutions-v1' or not isinstance(catalog['institutions'],dict) or not catalog['institutions']:
        raise RegistryError('Expected nonempty pl-institutions-v1 catalog')
    names=set()
    for key,descriptor in catalog['institutions'].items():
        if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9-]*',key) or not isinstance(descriptor,dict) or set(descriptor)!={'shortName','longName','displayTimezone','uidRegexp'}:
            raise RegistryError('Closed institution descriptor required')
        for field in ('shortName','longName','displayTimezone'):
            value=descriptor[field]
            if not isinstance(value,str) or not value or value.strip()!=value:raise RegistryError('Explicit institution names and timezone required')
        if descriptor['shortName'] in names:raise RegistryError('Duplicate native institution shortName')
        names.add(descriptor['shortName'])
        try:ZoneInfo(descriptor['displayTimezone'])
        except (ZoneInfoNotFoundError,ValueError) as error:raise RegistryError('Unknown institution timezone') from error
        regexp=descriptor['uidRegexp']
        if regexp is not None and (not isinstance(regexp,str) or not regexp.startswith('@') or not regexp.endswith('$') or re.search(r'(^|[^\\])(?:\\\\)*\.',regexp)):
            raise RegistryError('Native UID regexp must begin @, end $, and escape periods')
    return catalog['institutions']

def validate_registry(registry, images, institutions=None):
    if not isinstance(registry,dict) or set(registry)!={'schema','courses'} or registry['schema'] not in ('pl-courses-v1','pl-courses-v2') or not isinstance(registry['courses'],list) or not registry['courses']:
        raise RegistryError('Expected nonempty versioned native course registry')
    descriptors=validate_institutions(institutions) if registry['schema']=='pl-courses-v2' else None
    if not isinstance(images,dict): raise RegistryError('Missing image lock')
    pl=images.get('prairielearn',{}); grader=images.get('javaGrader',{})
    if not isinstance(pl,dict) or not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',str(pl.get('image',''))):
        raise RegistryError('PrairieLearn image requires an exact digest')
    if not isinstance(grader,dict) or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(grader.get('localImageId',''))) or not re.fullmatch(r'[^\s]+:[A-Za-z0-9][A-Za-z0-9_.-]*',str(grader.get('localImage',''))) or str(grader['localImage']).endswith(':latest'):
        raise RegistryError('Local Java grader requires a versioned image and verified image ID')
    ids=set(); mounts=set()
    for course in registry['courses']:
        fields={'id','repository','commit','mount'}|({'institution'} if descriptors is not None else set())
        if not isinstance(course,dict) or set(course)!=fields or not all(isinstance(v,str) for v in course.values()):
            raise RegistryError('Every course requires explicit string fields')
        if descriptors is not None and course['institution'] not in descriptors:raise RegistryError('Unknown institution key')
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
    parser.add_argument('--institutions',type=Path,default=INSTITUTIONS)
    args=parser.parse_args()
    try:
        registry=json.loads(args.registry.read_text())
        catalog=json.loads(args.institutions.read_text()) if isinstance(registry,dict) and registry.get('schema')=='pl-courses-v2' else None
        courses=validate_registry(registry,json.loads(args.images.read_text()),catalog)
    except (RegistryError,OSError,ValueError) as error: parser.exit(1,f'Registry rejected: {error}\n')
    print(f'Validated {len(courses)} exact course pins')

if __name__=='__main__': main()
