#!/usr/bin/env python3
"""Assemble a native PL course from a clean source checkout and owner exports."""
import argparse
import ctypes
import fcntl
import stat
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import importlib.util

_private_spec=importlib.util.spec_from_file_location('private_source',Path(__file__).with_name('prepare-private-source.py'))
_private=importlib.util.module_from_spec(_private_spec);_private_spec.loader.exec_module(_private)

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
        if 'id' in question and 'alternatives' in question:raise BuildError('id and alternatives cannot coexist')
        if 'alternatives' in question and question.get('numberChoose')!=1:raise BuildError('A random slot requires numberChoose1')
        if 'id' in question:
            if not isinstance(question['id'], str) or question['id'] not in questions:
                raise BuildError(f'Assessment refers to an absent question: {question["id"]}')
        elif 'alternatives' not in question:
            raise BuildError('Assessment question requires an id or alternatives')
        if 'alternatives' in question:
            alternatives = question['alternatives']
            if not isinstance(alternatives, list) or len(alternatives)<2:
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
            if zone.get('numberChoose') is not None:raise BuildError('Zone subset selection is unsupported')
            for question in zone['questions']:
                visit(question)

def publish_directory(source, destination, *, source_fd=-100, destination_fd=-100):
    # Linux renameat2 makes the no-replacement promise atomic, including an
    # empty directory created by another builder after our initial validation.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(source_fd, os.fsencode(source if source_fd==-100 else source.name), destination_fd, os.fsencode(destination if destination_fd==-100 else destination.name), 1):
        error = ctypes.get_errno()
        raise BuildError(f'Cannot publish fresh output: {os.strerror(error)}')

def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)

class _ExportStage:
    """Локальный filesystem lifecycle под protected/exclusive-writer предпосылкой."""
    def __init__(self, source, output, selected, inputs):
        self.output=output;self.parent=output.parent;self.parent_fd=None;self.fd=None
        self.products={};self.published=False;self.created=False
        if selected is None:
            self.path=self.parent/('.pl-full-export-'+uuid.uuid4().hex)
        else:
            text=os.fspath(selected)
            if not os.path.isabs(text) or os.path.normpath(text)!=text:
                raise BuildError('Export stage must be an absolute normalized path')
            self.path=Path(text)
        if self.path.parent!=self.parent or self.path in (output,output.with_name(output.name+'-checks.json')):
            raise BuildError('Export stage must be a distinct fresh sibling of output')
        for value in (source,*inputs):
            value=Path(value).absolute()
            if self.path.is_relative_to(value) or value.is_relative_to(self.path):
                raise BuildError('Export stage overlaps an immutable input')

    def __enter__(self):
        try:
            self.parent_fd=os.open(self.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            fcntl.flock(self.parent_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.parent_identity=_identity(os.fstat(self.parent_fd))
            self._parent_current()
            os.mkdir(self.path.name,0o700,dir_fd=self.parent_fd);self.created=True
            self.fd=os.open(self.path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.parent_fd)
            if stat.S_IMODE(os.fstat(self.fd).st_mode)!=0o700:
                raise BuildError('Export stage must have mode0700')
            self.identity=_identity(os.fstat(self.fd));self.assert_current()
            return self
        except BaseException as primary:
            if self.created:primary.add_note(f'Stage creation interrupted; retained for inspection: {self.path}')
            # Never remove a name whose created directory identity was not retained.
            self.close()
            raise

    def _parent_current(self):
        if self.parent.resolve()!=self.parent or _identity(self.parent.lstat())!=self.parent_identity:
            raise BuildError('Export parent identity changed')

    def assert_current(self, products=False):
        self._parent_current()
        if _identity(os.stat(self.path.name,dir_fd=self.parent_fd,follow_symlinks=False))!=self.identity:
            raise BuildError('Export stage identity changed')
        if products:
            for name,(fd,identity) in self.products.items():
                if _identity(os.stat(name,dir_fd=self.fd,follow_symlinks=False))!=identity:
                    raise BuildError('Export product identity changed: '+name)

    def bind_products(self):
        self.assert_current()
        for name,kind in [('native',stat.S_IFDIR),('checks.json',stat.S_IFREG)]:
            before=os.stat(name,dir_fd=self.fd,follow_symlinks=False)
            if stat.S_IFMT(before.st_mode)!=kind:
                raise BuildError('Invalid export product type: '+name)
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|(os.O_DIRECTORY if kind==stat.S_IFDIR else 0),dir_fd=self.fd)
            info=os.fstat(fd)
            if stat.S_IFMT(info.st_mode)!=kind or _identity(info)!=_identity(before):
                os.close(fd);raise BuildError('Invalid export product type or identity: '+name)
            self.products[name]=(fd,_identity(info))
        self.assert_current(products=True)

    def observe_publication(self):
        native=self.products.get("native")
        if native:
            try:self.published |= _identity(os.stat(self.output.name,dir_fd=self.parent_fd,follow_symlinks=False))==native[1]
            except FileNotFoundError:pass
        return self.published

    def private_checks_current(self, name, identity):
        self.assert_current()
        if _identity(os.stat(name,dir_fd=self.parent_fd,follow_symlinks=False))!=identity:
            raise BuildError("Private checks output identity changed; preserved")

    def remove_private_checks(self, name, identity):
        self.assert_current()
        if _identity(os.stat(name,dir_fd=self.parent_fd,follow_symlinks=False))!=identity:
            raise BuildError('Private checks output identity changed; preserved')
        os.unlink(name,dir_fd=self.parent_fd)

    @staticmethod
    def _clear_directory(fd):
        # All recursion stays anchored to our retained directory, never a fresh
        # resolution of export-stage. Symlinks are unlinked, never traversed.
        # Новый directory stream видит entries, созданные после первоначального
        # open пустого stage. Относительный "." остаётся на том же held inode.
        reader=os.open('.',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            if _identity(os.fstat(reader))!=_identity(os.fstat(fd)):
                raise BuildError('Stage directory identity changed before cleanup read')
            names=os.listdir(reader)
        finally:os.close(reader)
        for name in names:
            info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    if _identity(os.fstat(child))!=_identity(info):
                        raise BuildError('Stage child replaced during cleanup')
                    _ExportStage._clear_directory(child)
                    if _identity(os.stat(name,dir_fd=fd,follow_symlinks=False))!=_identity(info):
                        raise BuildError('Stage child replaced during cleanup')
                    os.rmdir(name,dir_fd=fd)
                finally:os.close(child)
            else:os.unlink(name,dir_fd=fd)

    def close(self):
        for fd,_ in self.products.values():os.close(fd)
        self.products.clear()
        if self.fd is not None:os.close(self.fd);self.fd=None
        if self.parent_fd is not None:os.close(self.parent_fd);self.parent_fd=None

    def __exit__(self, kind, primary, traceback):
        try:
            self.assert_current()
            self._clear_directory(self.fd)
            self.assert_current()
            os.rmdir(self.path.name,dir_fd=self.parent_fd)
        except BaseException as error:
            outcome=f'Export cleanup refused; published={self.published}; stage={self.path}; {error}'
            if primary is not None:primary.add_note(outcome)
            else:raise BuildError(outcome) from error
        finally:self.close()
        return False

def build_course(source: Path, book: str, instance: str, output: Path, runtime_registry=None, candidate_image=None, staging_receipt=None, export_stage=None) -> None:
    source=Path(source).absolute();output=Path(output).absolute()
    if source.resolve()!=source or source.is_symlink():raise BuildError('Source must be an absolute real checkout')
    if output.exists() or output.is_symlink() or output.is_relative_to(source):raise BuildError('Output must be fresh and outside source')
    if not output.parent.is_dir() or output.parent.resolve()!=output.parent:raise BuildError('Output parent must be real existing directory')
    if git(source,'status','--porcelain','--untracked-files=all'):raise BuildError('Source checkout must be clean before export')
    staging=None;staging_sha=None
    if staging_receipt:
        staging_sha=hashlib.sha256(Path(staging_receipt).read_bytes()).hexdigest()
        try:staging=_private.validate(source,staging_receipt)
        except (_private.StageError,OSError) as error:raise BuildError('Private staging receipt validation failed') from error
        if staging['publicBase']['book']!=book:raise BuildError('Staging receipt book mismatch')
        repository=staging['publicBase']['repository']
    else:
        repository=git(source,'remote','get-url','origin')
        if not re.fullmatch(r'https://[^/@\s]+/[^\s]+',repository):raise BuildError('Origin must be credential-free HTTPS')
    commit=git(source,'rev-parse','HEAD');root=relative_path(source,book)
    entries=[root/'_extensions/course-prairielearn/entrypoints/export-course.ts',root/'_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export-course.ts']
    entries=[p for p in entries if p.is_file() and not p.is_symlink()]
    if len(entries)!=1:raise BuildError('Exactly one installed full owner exporter is required')
    if entries[0].resolve()!=entries[0]:raise BuildError('Installed full owner exporter must not use aliased parents')
    registry=Path(runtime_registry or PLATFORM/'runtime-profiles.json').absolute()
    immutable_inputs=[registry]+([Path(staging_receipt)] if staging_receipt else [])
    with _ExportStage(source,output,export_stage,immutable_inputs) as owned:
        stage=owned.path;native=stage/'native';checks=stage/'checks.json'
        command=['quarto','run',str(entries[0]),str(source),str(native),'--instance',instance,'--checks-output',str(checks),'--runtime-registry',str(registry),'--book',book]
        if candidate_image:command+=['--candidate-image',candidate_image]
        if staging:command+=['--staging-receipt',str(Path(staging_receipt).absolute())]
        try:subprocess.run(command,cwd=root,check=True)
        except (OSError,subprocess.CalledProcessError) as error:raise BuildError('Installed full owner export failed') from error
        owned.bind_products()
        files=tree(native)
        owned.assert_current(products=True)
        if 'delivery.json' not in files or 'infoCourse.json' not in files or not checks.is_file():raise BuildError('Full exporter did not emit native course, delivery and private checks')
        delivery=read_json(native/'delivery.json');manifest=read_json(checks)
        checks_text=checks.read_text()
        if json.loads(checks_text)!=manifest:raise BuildError('Private checks changed during validation')
        from delivery_verification import package_integrity
        from grading_job import JobError
        try:
            # Closed3/4 kind-specific package checks; no fake code Job for Internal/Workspace.
            package_integrity(delivery,native,manifest)
        except (JobError,OSError,ValueError,KeyError,TypeError) as error:
            raise BuildError('Delivery/check package validation failed: '+str(error)) from error
        validate_uuids_and_assessments(native,delivery['questions'])
        provenance={'schema':'pl-provenance-v1','source':{'repository':repository,'commit':commit,'dirty':False,'book':book,'instance':instance},'builder': {'repository':'https://github.com/Afonenko-Course-Tools/prairielearn-platform','commit':git(PLATFORM,'rev-parse','HEAD'),'dirty':bool(git(PLATFORM,'status','--porcelain','--untracked-files=all'))},'deliveryHash':delivery['deliveryHash'],'sourceSnapshotHash':delivery['sourceSnapshotHash'],'inventoryHash':delivery['inventoryHash'],'platformImages':read_json(PLATFORM/'images.lock.json'),'files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
        if staging:
            provenance['source']={'mode':'private-stage','publicBase':staging['publicBase'],'privateStage':staging['privateStage'],'stagingReceiptSha256':staging_sha,'materialization':staging['materialization'],'seedFiles':staging['seedFiles'],'seedStorage':staging['seedStorage'],'dirty':False,'book':book,'instance':instance}
        if git(source,'status','--porcelain','--untracked-files=all') or git(source,'rev-parse','HEAD')!=commit:raise BuildError('Exporter changed clean source')
        if staging:
            try:
                if _private.validate(source,staging_receipt,allow_runtime=True)!=staging or hashlib.sha256(Path(staging_receipt).read_bytes()).hexdigest()!=staging_sha:raise _private.StageError('Receipt changed')
                provenance['source']['runtimeInventory']=_private.runtime_inventory(source,staging)
            except (_private.StageError,OSError) as error:raise BuildError('Exporter changed private staging inventory') from error
        owned.assert_current(products=True)
        write_json(native/'provenance.json',provenance)
        # Checks inventory stays private outside native payload.
        checks_output=output.parent/(output.name+'-checks.json')
        if checks_output.exists():raise BuildError('Private checks output must be fresh')
        try:
            owned.assert_current(products=True)
            if checks.read_text()!=checks_text:raise BuildError('Private checks changed before publication')
            with checks_output.open('x') as f:
                private_identity=_identity(os.fstat(f.fileno()))
                try:
                    f.write(checks_text);f.flush()
                    if {n:b for n,b in tree(native).items() if n!='provenance.json'}!=files:raise BuildError('Native inventory changed before publication')
                    owned.assert_current(products=True)
                    owned.private_checks_current(checks_output.name,private_identity)
                    publish_directory(native,output,source_fd=owned.fd,destination_fd=owned.parent_fd)
                    owned.published=True
                except BaseException as primary:
                    try:
                        if owned.observe_publication():primary.add_note(f'Native already published at {output}; private checks preserved at {checks_output}')
                        else:owned.remove_private_checks(checks_output.name,private_identity)
                    except BaseException as cleanup:primary.add_note("Private checks cleanup refused: "+str(cleanup))
                    raise
        except OSError as error:
            failure=BuildError('Native candidate exported but private checks publication failed')
            for note in getattr(error,'__notes__',[]):failure.add_note(note)
            raise failure from error

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True,type=Path);parser.add_argument('--book',default='tasks');parser.add_argument('--instance',required=True);parser.add_argument('--output',required=True,type=Path);parser.add_argument('--runtime-registry',type=Path);parser.add_argument('--candidate-image');parser.add_argument('--staging-receipt',type=Path);parser.add_argument('--export-stage',help='Fresh absolute sibling export stage selected before qualification');args=parser.parse_args()
    try:build_course(args.source,args.book,args.instance,args.output,args.runtime_registry,args.candidate_image,args.staging_receipt,args.export_stage)
    except (BuildError,OSError) as error:parser.exit(1,f'Course export rejected: {error}\n'+''.join(note+'\n' for note in getattr(error,'__notes__',[])))
if __name__=='__main__':main()
