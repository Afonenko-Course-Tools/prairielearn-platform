#!/usr/bin/env python3
"""Assemble a native PL course from a clean source checkout and owner exports."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

PLATFORM = Path(__file__).resolve().parents[1]
ID = re.compile(r'[a-z][a-z0-9-]*\Z')
QID = re.compile(r'[a-z][a-z0-9-]*/exr-[a-z0-9][a-z0-9-]*\Z')

class BuildError(Exception):
    pass

def read_json(path):
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise BuildError(f'Expected a JSON object: {path}')
        return value
    except (OSError, ValueError) as error:
        raise BuildError(f'Cannot read JSON: {path}') from error

def relative_path(root, name):
    if not isinstance(name, str) or not name or '\\' in name or '\0' in name:
        raise BuildError(f'Invalid relative path: {name!r}')
    p = Path(name)
    if p.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
        raise BuildError(f'Unsafe relative path: {name!r}')
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise BuildError(f'Symlink is forbidden: {current}')
    return current

def tree(root):
    if not root.is_dir() or root.is_symlink():
        raise BuildError(f'Expected a real directory: {root}')
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise BuildError(f'Symlink is forbidden: {p}')
        if p.is_file():
            result[p.relative_to(root).as_posix()] = p.read_bytes()
        elif not p.is_dir():
            raise BuildError(f'Special file is forbidden: {p}')
    return result

def git(root, *args):
    try:
        return subprocess.run(['git', *args], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise BuildError(f'Git source validation failed: {root}') from error

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')

def validate_uuids_and_assessments(course, questions):
    seen = {}
    native = [course/'infoCourse.json']
    native += sorted((course/'courseInstances').rglob('infoCourseInstance.json'))
    assessments = sorted((course/'courseInstances').rglob('infoAssessment.json'))
    native += assessments
    native += [course/'questions'/qid/'info.json' for qid in sorted(questions)]
    for path in native:
        value = read_json(path)
        if 'uuid' not in value and path.name == 'infoCourse.json':
            continue
        try:
            key = str(uuid.UUID(value['uuid']))
        except (ValueError, TypeError, KeyError) as error:
            raise BuildError(f'Missing or invalid UUID: {path}') from error
        if key in seen:
            raise BuildError(f'UUID collision: {path} and {seen[key]}')
        seen[key] = path
    def visit(question):
        if not isinstance(question, dict):
            raise BuildError('Assessment question must be an object')
        if 'id' in question:
            if not isinstance(question['id'], str) or question['id'] not in questions:
                raise BuildError(f'Assessment refers to an absent question: {question["id"]}')
        elif 'alternatives' not in question:
            raise BuildError('Assessment question requires an id or alternatives')
        if 'alternatives' in question:
            alternatives = question['alternatives']
            if not isinstance(alternatives, list) or not alternatives:
                raise BuildError('Question alternatives must be a nonempty list')
            for alternative in alternatives:
                visit(alternative)
    for path in assessments:
        zones = read_json(path).get('zones', [])
        if not isinstance(zones, list):
            raise BuildError(f'Assessment zones must be a list: {path}')
        for zone in zones:
            if not isinstance(zone, dict) or not isinstance(zone.get('questions'), list):
                raise BuildError(f'Assessment zone requires a questions list: {path}')
            for question in zone['questions']:
                visit(question)

def publish_directory(source, destination):
    # Linux renameat2 makes the no-replacement promise atomic, including an
    # empty directory created by another builder after our initial validation.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise BuildError(f'Cannot publish fresh output: {os.strerror(error)}')

def _build_course(source: Path, config: Path, output: Path) -> None:
    source = Path(source).absolute()
    if source.is_symlink() or source.resolve() != source:
        raise BuildError('Source path must not contain symlinks')
    config = Path(config).absolute()
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise BuildError('Output must be a fresh path')
    if output.parent.resolve() != output.parent or not output.parent.is_dir():
        raise BuildError('Output parent must be an existing real directory')
    if output.is_relative_to(source):
        raise BuildError('Output must be outside the source checkout')
    try:
        config_name = config.relative_to(source).as_posix()
    except ValueError as error:
        raise BuildError('Config must be inside source checkout') from error
    relative_path(source, config_name)
    if git(source, 'status', '--porcelain', '--untracked-files=all'):
        raise BuildError('Source checkout must be clean before export')
    source_commit = git(source, 'rev-parse', 'HEAD')
    repository = git(source, 'remote', 'get-url', 'origin')
    if not re.fullmatch(r'https://[^/@\s]+/[^\s]+', repository):
        raise BuildError('Source origin must be an HTTPS URL without credentials')
    cfg = read_json(config)
    if not isinstance(cfg, dict) or set(cfg) != {'schema','courseId','book','works','shell'} or cfg['schema'] != 'pl-source-v1':
        raise BuildError('Expected pl-source-v1 config with explicit fields')
    course_id = cfg['courseId']
    if not isinstance(course_id, str) or not ID.fullmatch(course_id):
        raise BuildError('Invalid course ID')
    book = relative_path(source, cfg['book'])
    shell = relative_path(source, cfg['shell'])
    entry = relative_path(book, '_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export.ts')
    if not entry.is_file():
        raise BuildError('Installed owner exporter is missing')
    works = cfg['works']
    if not isinstance(works, list) or not works:
        raise BuildError('At least one work is required')
    ids = set()
    for work in works:
        if not isinstance(work, dict) or set(work) != {'id','binding'} or not isinstance(work['id'], str) or not ID.fullmatch(work['id']) or work['id'] in ids:
            raise BuildError('Invalid or duplicate work')
        ids.add(work['id'])
        if not relative_path(source, work['binding']).is_file():
            raise BuildError('Work binding is missing')
    manifests = {}
    for name in ('providers.json','installed-packages.json'):
        p = relative_path(source, name)
        manifests[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    shell_files = tree(shell)
    if 'infoCourse.json' not in shell_files:
        raise BuildError('Native shell requires infoCourse.json')
    if any(n != 'infoCourse.json' and not n.startswith('courseInstances/') for n in shell_files):
        raise BuildError('Native shell may contain only course and instance files')
    with tempfile.TemporaryDirectory(prefix='.pl-build-', dir=output.parent) as temporary:
        stage = Path(temporary); native = stage/'native'; native.mkdir()
        for name, content in shell_files.items():
            p = native/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(content)
        questions = {}; grading_images = set()
        for work in works:
            exported = stage/('export-'+work['id'])
            try:
                subprocess.run(['quarto','run',str(entry.relative_to(source)),'.',cfg['book'],work['id'],work['binding'],str(exported)], cwd=source, check=True)
            except (OSError, subprocess.CalledProcessError) as error:
                raise BuildError(f'Owner export failed: {work["id"]}') from error
            files = tree(exported)
            if any(n != 'delivery.json' and not n.startswith('questions/') for n in files):
                raise BuildError('Unexpected file in owner export')
            delivery = read_json(exported/'delivery.json')
            qids = delivery.get('questions')
            exported_works = delivery.get('works')
            if delivery.get('course') != course_id or not isinstance(qids, list) or not qids or not all(isinstance(q, str) and QID.fullmatch(q) and q.startswith(course_id+'/') for q in qids) or len(set(qids)) != len(qids):
                raise BuildError('Delivery course namespace or questions disagree')
            if not isinstance(exported_works, list) or len(exported_works) != 1:
                raise BuildError('Owner export must contain one work')
            w = exported_works[0]
            if not isinstance(w, dict) or not isinstance(w.get('assignments'), dict):
                raise BuildError('Delivery work requires an assignments object')
            if w.get('owner') != course_id or w.get('id') != work['id'] or w.get('key') != course_id+'/'+work['id'] or w.get('items') != qids or set(w.get('assignments', {})) != set(qids):
                raise BuildError('Delivery membership or assignments disagree')
            for assignment in w['assignments'].values():
                if not isinstance(assignment, dict) or assignment.get('requirement') not in ('required','optional') or assignment.get('workMode') not in ('individual','pair','group'):
                    raise BuildError('Invalid work assignment')
            claimed = {'delivery.json'}
            for qid in qids:
                prefix = 'questions/'+qid+'/'
                content = {n[len(prefix):]:b for n,b in files.items() if n.startswith(prefix)}
                if 'info.json' not in content or 'question.html' not in content:
                    raise BuildError(f'Incomplete question: {qid}')
                claimed.update(prefix+n for n in content)
                if qid in questions:
                    if questions[qid] != content:
                        raise BuildError(f'Conflicting duplicate question: {qid}')
                    continue
                questions[qid] = content
                for name, data in content.items():
                    p = native/'questions'/qid/name;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(data)
                info = read_json(native/'questions'/qid/'info.json')
                options = info.get('externalGradingOptions', {})
                if not isinstance(options, dict):
                    raise BuildError('External grading options must be an object')
                image = options.get('image')
                if image is not None and not isinstance(image, str):
                    raise BuildError('Grading image must be a string')
                if image:
                    grading_images.add(image)
            if claimed != set(files):
                raise BuildError('Unclaimed questions in owner export')
            write_json(native/'deliveries'/(work['id']+'.json'), delivery)
        validate_uuids_and_assessments(native, questions)
        lock = read_json(PLATFORM/'images.lock.json')
        provenance = {'schema':'pl-provenance-v1','source':{'repository':repository,'commit':source_commit,'dirty':False,'config':config_name,'manifests':manifests},'builder':{'repository':'https://github.com/Afonenko-Course-Tools/prairielearn-platform','commit':git(PLATFORM,'rev-parse','HEAD'),'dirty':bool(git(PLATFORM,'status','--porcelain','--untracked-files=all'))},'gradingImages':sorted(grading_images),'platformImages':lock,'files':{n:hashlib.sha256(b).hexdigest() for n,b in tree(native).items()}}
        write_json(native/'provenance.json', provenance)
        if git(source, 'diff', '--name-only', 'HEAD'):
            raise BuildError('Export changed tracked source files')
        if output.exists() or output.is_symlink():
            raise BuildError('Output appeared during build')
        publish_directory(native, output)

def build_course(source: Path, config: Path, output: Path) -> None:
    try:
        _build_course(source, config, output)
    except OSError as error:
        raise BuildError(f'Course filesystem operation failed: {error.strerror}') from error

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        build_course(args.source,args.config,args.output)
    except BuildError as error:
        parser.exit(1, f'Course build rejected: {error}\n')

if __name__ == '__main__':
    main()
