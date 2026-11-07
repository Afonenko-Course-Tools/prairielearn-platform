#!/usr/bin/env python3
"""Проверка точных native-course pins до checkout или развёртывания."""
import argparse
import json
from pathlib import Path
import re
from typing import NotRequired, TypeGuard, TypedDict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RegistryError(Exception):
    pass


class Institution(TypedDict):
    shortName: str
    longName: str
    displayTimezone: str
    uidRegexp: str | None


class Course(TypedDict):
    id: str
    repository: str
    commit: str
    mount: str
    institution: NotRequired[str]


INSTITUTIONS = Path(__file__).resolve().parents[1] / 'config/institutions.json'


def _object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _string(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise RegistryError(message)
    return value


def validate_institutions(catalog: object) -> dict[str, Institution]:
    if (not _object(catalog) or set(catalog) != {'schema', 'institutions'}
            or catalog['schema'] != 'pl-institutions-v1'):
        raise RegistryError('Expected nonempty pl-institutions-v1 catalog')
    entries = catalog['institutions']
    if not _object(entries) or not entries:
        raise RegistryError('Expected nonempty pl-institutions-v1 catalog')
    names: set[str] = set()
    result: dict[str, Institution] = {}
    for key, descriptor in entries.items():
        if (not isinstance(key, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', key)
                or not _object(descriptor)
                or set(descriptor) != {'shortName', 'longName', 'displayTimezone', 'uidRegexp'}):
            raise RegistryError('Closed institution descriptor required')
        fields: dict[str, str] = {}
        for field in ('shortName', 'longName', 'displayTimezone'):
            value = _string(descriptor[field], 'Explicit institution names and timezone required')
            if not value or value.strip() != value:
                raise RegistryError('Explicit institution names and timezone required')
            fields[field] = value
        if fields['shortName'] in names:
            raise RegistryError('Duplicate native institution shortName')
        names.add(fields['shortName'])
        try:
            ZoneInfo(fields['displayTimezone'])
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise RegistryError('Unknown institution timezone') from error
        regexp = descriptor['uidRegexp']
        if regexp is not None and (not isinstance(regexp, str) or not regexp.startswith('@')
                or not regexp.endswith('$') or re.search(r'(^|[^\\])(?:\\\\)*\.', regexp)):
            raise RegistryError('Native UID regexp must begin @, end $, and escape periods')
        result[key] = Institution(shortName=fields['shortName'], longName=fields['longName'],
                                  displayTimezone=fields['displayTimezone'], uidRegexp=regexp)
    return result


def validate_registry(registry: object, images: object, institutions: object = None) -> list[Course]:
    if (not _object(registry) or set(registry) != {'schema', 'courses'}
            or registry['schema'] not in ('pl-courses-v1', 'pl-courses-v2')):
        raise RegistryError('Expected nonempty versioned native course registry')
    courses = registry['courses']
    if not _list(courses) or not courses:
        raise RegistryError('Expected nonempty versioned native course registry')
    descriptors = validate_institutions(institutions) if registry['schema'] == 'pl-courses-v2' else None
    if not _object(images):
        raise RegistryError('Missing image lock')
    pl, grader = images.get('prairielearn'), images.get('javaGrader')
    if not _object(pl) or not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', str(pl.get('image', ''))):
        raise RegistryError('PrairieLearn image requires an exact digest')
    if (not _object(grader)
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(grader.get('localImageId', '')))
            or not re.fullmatch(r'[^\s]+:[A-Za-z0-9][A-Za-z0-9_.-]*', str(grader.get('localImage', '')))
            or str(grader['localImage']).endswith(':latest')):
        raise RegistryError('Local Java grader requires a versioned image and verified image ID')
    ids: set[str] = set()
    mounts: set[str] = set()
    result: list[Course] = []
    for raw in courses:
        fields: set[str] = {'id', 'repository', 'commit', 'mount'} | ({'institution'} if descriptors is not None else set())
        if not _object(raw) or set(raw) != fields:
            raise RegistryError('Every course requires explicit string fields')
        course = Course(id=_string(raw['id'], 'Every course requires explicit string fields'),
                        repository=_string(raw['repository'], 'Every course requires explicit string fields'),
                        commit=_string(raw['commit'], 'Every course requires explicit string fields'),
                        mount=_string(raw['mount'], 'Every course requires explicit string fields'))
        if descriptors is not None:
            institution = _string(raw['institution'], 'Every course requires explicit string fields')
            if institution not in descriptors:
                raise RegistryError('Unknown institution key')
            course['institution'] = institution
        if not re.fullmatch(r'[a-z][a-z0-9-]*', course['id']) or course['id'] in ids:
            raise RegistryError('Invalid or duplicate course ID')
        if not re.fullmatch(r'[a-f0-9]{40}', course['commit']):
            raise RegistryError('Course requires an exact Git commit')
        if not re.fullmatch(r'/course(?:[2-9]|[1-9][0-9]+)?', course['mount']) or course['mount'] in mounts:
            raise RegistryError('Invalid or duplicate native mount')
        url = course['repository']
        try:
            parsed = urlsplit(url)
        except ValueError as error:
            raise RegistryError('Invalid repository URL') from error
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or not parsed.path.strip('/')
                or re.search(r'[\s\\%]', url) or '..' in parsed.path.split('/')):
            raise RegistryError('Repository requires a credential-free HTTPS URL')
        ids.add(course['id'])
        mounts.add(course['mount'])
        result.append(course)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('registry', type=Path)
    parser.add_argument('--images', type=Path, default=Path(__file__).resolve().parents[1] / 'images.lock.json')
    parser.add_argument('--institutions', type=Path, default=INSTITUTIONS)
    args = parser.parse_args()
    try:
        registry: object = json.loads(args.registry.read_text())
        catalog: object = (json.loads(args.institutions.read_text())
                           if _object(registry) and registry.get('schema') == 'pl-courses-v2' else None)
        courses = validate_registry(registry, json.loads(args.images.read_text()), catalog)
    except (RegistryError, OSError, ValueError) as error:
        parser.exit(1, f'Registry rejected: {error}\n')
    print(f'Validated {len(courses)} exact course pins')


if __name__ == '__main__':
    main()
