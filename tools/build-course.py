#!/usr/bin/env python3
"""Собрать Native-курс штатным установленным экспортёром."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import tempfile
import shutil
import sys
from typing import TypeGuard
sys.path.insert(0, str(Path(__file__).resolve().parent))
from json_boundary import JSONObject, is_object, is_list, json_object

PLATFORM = Path(__file__).resolve().parents[1]
ID = re.compile(r'[a-z][a-z0-9-]*\Z')
QID = re.compile(r'[a-z][a-z0-9-]*/exr-[a-z0-9][a-z0-9-]*\Z')

class BuildArguments(argparse.Namespace):
    source: Path
    book: str
    instance: str
    output: Path
    runtime_registry: Path | None
    candidate_image: str | None
    export_stage: str | None


class BuildError(Exception):
    pass

def read_json(path: Path) -> JSONObject:
    try:
        return json_object(json.loads(path.read_text()))
    except (OSError, ValueError) as error:
        raise BuildError(f'Cannot read JSON: {path}') from error

def relative_path(root: Path, name: object) -> Path:
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

def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')

def _question_ids(value: object) -> TypeGuard[list[str]]:
    return is_list(value) and all(isinstance(item, str) for item in value)


def validate_uuids_and_assessments(course: Path, questions: object) -> None:
    if not _question_ids(questions):
        raise BuildError('Expected a question ID list')
    seen: dict[str, Path] = {}
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
            identity = value['uuid']
            if not isinstance(identity, str):
                raise BuildError(f'Missing or invalid UUID: {path}')
            key = str(uuid.UUID(identity))
        except (ValueError, TypeError, KeyError) as error:
            raise BuildError(f'Missing or invalid UUID: {path}') from error
        if key in seen:
            raise BuildError(f'UUID collision: {path} and {seen[key]}')
        seen[key] = path
    def visit(question: object) -> None:
        if not is_object(question):
            raise BuildError('Assessment question must be an object')
        if 'id' in question and 'alternatives' in question:raise BuildError('id and alternatives cannot coexist')
        if 'alternatives' in question and question.get('numberChoose')!=1:raise BuildError('A random slot requires numberChoose1')
        if 'id' in question:
            if not isinstance(question['id'], str) or question['id'] not in questions:
                raise BuildError(f'Assessment refers to an absent question: {question["id"]}')
        elif 'alternatives' not in question:
            raise BuildError('Assessment question requires an id or alternatives')
        if 'alternatives' in question:
            alternatives = question['alternatives']
            if not is_list(alternatives) or len(alternatives)<2:
                raise BuildError('Question alternatives must be a nonempty list')
            for alternative in alternatives:
                visit(alternative)
    for path in assessments:
        zones = read_json(path).get('zones', [])
        if not isinstance(zones, list):
            raise BuildError(f'Assessment zones must be a list: {path}')
        for zone in zones:
            if not isinstance(zone, dict):
                raise BuildError(f'Assessment zone requires a questions list: {path}')
            entries = zone.get('questions')
            if not isinstance(entries, list):
                raise BuildError(f'Assessment zone requires a questions list: {path}')
            if zone.get('numberChoose') is not None:raise BuildError('Zone subset selection is unsupported')
            for question in entries:
                visit(question)

def publish_directory(source: Path, destination: Path, *, source_fd: int = -100, destination_fd: int = -100) -> None:
    # Linux renameat2 makes the no-replacement promise atomic, including an
    # empty directory created by another builder after our initial validation.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source if source_fd==-100 else source.name), destination_fd, os.fsencode(destination if destination_fd==-100 else destination.name), 1):
        error = ctypes.get_errno()
        raise BuildError(f'Cannot publish fresh output: {os.strerror(error)}')

def build_course(source: Path, book: str, instance: str, output: Path, runtime_registry: str | Path | None = None, candidate_image: str | None = None, export_stage: str | Path | None = None) -> None:
    source=Path(source).absolute();output=Path(output).absolute()
    if source.resolve()!=source or not source.is_dir():raise BuildError('Source must be an absolute real checkout')
    if output.exists() or output.is_symlink() or output.is_relative_to(source):raise BuildError('Output must be fresh and outside source')
    if not output.parent.is_dir() or output.parent.resolve()!=output.parent:raise BuildError('Output parent must be real existing directory')
    root=relative_path(source,book)
    entries=[root/'_extensions/course-prairielearn/entrypoints/export-course.ts',root/'_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export-course.ts']
    entries=[p for p in entries if p.is_file() and not p.is_symlink()]
    if len(entries)!=1 or entries[0].resolve()!=entries[0]:raise BuildError('Exactly one installed full owner exporter is required')
    registry=Path(runtime_registry or PLATFORM/'runtime-profiles.json').absolute()
    checks_output=output.parent/(output.name+'-checks.json')
    if checks_output.exists() or checks_output.is_symlink():raise BuildError('Private checks output must be fresh')
    if export_stage is None:
        stage=Path(tempfile.mkdtemp(prefix='.pl-export-',dir=output.parent))
    else:
        text=os.fspath(export_stage)
        if not os.path.isabs(text) or os.path.normpath(text)!=text:raise BuildError('Export stage must be an absolute normalized path')
        stage=Path(text)
        if not stage.is_absolute() or stage.parent!=output.parent or stage in (output,checks_output) or stage.is_relative_to(source):raise BuildError('Export stage must be a fresh sibling of output')
        stage.mkdir(mode=0o700)
    try:
        native=stage/'native';checks=stage/'checks.json'
        command=['quarto','run',str(entries[0]),str(source),str(native),'--instance',instance,'--checks-output',str(checks),'--runtime-registry',str(registry),'--book',book]
        if candidate_image:command+=['--candidate-image',candidate_image]
        try:subprocess.run(command,cwd=root,check=True)
        except (OSError,subprocess.CalledProcessError) as error:raise BuildError('Installed full owner export failed') from error
        from delivery_verification import package_integrity
        from grading_job import JobError,inventory
        delivery=read_json(native/'delivery.json');manifest=read_json(checks)
        try:
            inventory(manifest);package_integrity(delivery,native,manifest)
        except (JobError,OSError,ValueError,KeyError,TypeError) as error:raise BuildError('Native package validation failed: '+str(error)) from error
        validate_uuids_and_assessments(native,delivery['questions'])
        # Приватные выбранные bytes находятся вне дерева, которое читает PL.
        with checks_output.open('x') as stream:
            os.chmod(checks_output,0o600);stream.write(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        try:publish_directory(native,output)
        except BaseException:
            if not output.exists():checks_output.unlink()
            raise
    finally:
        shutil.rmtree(stage)

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True,type=Path);parser.add_argument('--book',default='tasks');parser.add_argument('--instance',required=True);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--runtime-registry',type=Path);parser.add_argument('--candidate-image');parser.add_argument('--export-stage');args=parser.parse_args(namespace=BuildArguments())
    try:build_course(args.source,args.book,args.instance,args.output,args.runtime_registry,args.candidate_image,args.export_stage)
    except (BuildError,OSError) as error:parser.exit(1,f'Course export rejected: {error}\n')
if __name__=='__main__':main()
