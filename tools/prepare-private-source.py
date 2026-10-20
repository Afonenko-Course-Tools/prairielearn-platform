#!/usr/bin/env python3
"""Заморозить приватный source из публичного Git snapshot и точного Core receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

class StageError(Exception):
    pass

def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):
    try:return json.loads(path.read_bytes())
    except (OSError,ValueError) as error:raise StageError(f'Некорректный receipt: {path}') from error

def git(root,*args,data=None,env=None):
    result=subprocess.run(['git',*args],cwd=root,input=data,capture_output=True,env=env)
    if result.returncode:raise StageError('Git snapshot validation failed: '+result.stderr.decode(errors='replace'))
    return result.stdout.decode().strip()

def safe(root,name):
    if not isinstance(name,str) or not name or any(c in name for c in '\\\0:*?[]{}') or any(p in ('','.','..') for p in name.split('/')) or name.startswith('/'):
        raise StageError('Недопустимый относительный путь')
    result=root/name
    for parent in [result,*result.parents]:
        if parent==root.parent:break
        if parent.is_symlink():raise StageError('Символическая ссылка запрещена')
    return result

def inventory(root):
    result={}
    def walk(path):
        for child in sorted(path.iterdir()):
            if path==root and child.name=='.git':continue
            if child.is_symlink():raise StageError('Символическая ссылка в snapshot')
            if child.is_dir():walk(child)
            elif child.is_file():result[child.relative_to(root).as_posix()]=digest(child.read_bytes())
            else:raise StageError('Специальный файл в snapshot')
    walk(root)
    return result

def runtime_inventory(source,value):
    roots=value.get('runtimeRoots',[])
    expected=[value['publicBase']['book']+'/_generated',value['publicBase']['book']+'/.quarto','.quarto']
    if roots!=expected:raise StageError('Некорректные runtime roots')
    for name in roots:
        path=safe(source,name)
        if path.exists() and not path.is_dir():raise StageError('Runtime root должен быть каталогом')
    return {name:sha for name,sha in inventory(source).items() if any(name.startswith(root+'/') for root in roots)}

def validate(source,receipt,allow_runtime=False):
    source=Path(source).absolute();receipt=Path(receipt).absolute();value=read(receipt)
    if source.resolve()!=source or value.get('schema')!='pl-private-source-v1' or value.get('privateStage',{}).get('path')!=str(source):raise StageError('Receipt не принадлежит private stage')
    if git(source,'remote') or git(source,'status','--porcelain','--untracked-files=all'):raise StageError('Private stage должен быть clean и без remotes')
    if git(source,'rev-parse','HEAD')!=value['privateStage']['commit'] or git(source,'rev-parse','HEAD^{tree}')!=value['privateStage']['tree']:raise StageError('Private stage commit изменён')
    files=inventory(source);runtime=runtime_inventory(source,value)
    if allow_runtime:
        files={name:sha for name,sha in files.items() if name not in runtime}
    elif runtime or any((source/name).exists() for name in value['runtimeRoots']):raise StageError('До export runtime roots должны отсутствовать')
    if files!=value.get('files'):raise StageError('Private stage inventory изменён (включая ignored seed files)')
    return value

def prepare(public,book,core,output,receipt):
    public=Path(public).absolute();core=Path(core).absolute();output=Path(output).absolute();receipt=Path(receipt).absolute()
    for root in (public,core):
        if root.resolve()!=root or not root.is_dir():raise StageError('Требуется настоящий входной каталог')
    owner=safe(public,book)
    if output.exists() or receipt.exists() or output.is_symlink() or receipt.is_symlink():raise StageError('Output и receipt должны быть новыми')
    for root in (public,core):
        if output==root or output.is_relative_to(root) or root.is_relative_to(output):raise StageError('Output пересекается с source')
        if receipt==root or receipt.is_relative_to(root) or root.is_relative_to(receipt):raise StageError('Receipt пересекается с входным source/Core')
    if receipt.is_relative_to(output) or not output.parent.is_dir() or output.parent.resolve()!=output.parent or receipt.parent.resolve()!=receipt.parent:raise StageError('Receipt должен быть снаружи stage, родители — настоящими')
    if git(public,'status','--porcelain','--untracked-files=all'):raise StageError('Публичный source должен быть clean')
    repository=git(public,'remote','get-url','origin')
    if not re.fullmatch(r'https://[^/@\s]+/[^\s]+',repository):raise StageError('Origin должен быть credential-free HTTPS')
    commit=git(public,'rev-parse','HEAD');manifest_path=core/'materialization.json';manifest_bytes=manifest_path.read_bytes();manifest=read(manifest_path)
    if manifest.get('schema')!='course-project-materialization-v1' or manifest.get('audience')!='grading' or manifest.get('sourceRoot')!=str(owner):raise StageError('Требуется grading Core receipt данного owner')
    projects=manifest.get('projects',[])
    if not projects or len({p['exerciseId'] for p in projects})!=len(projects):raise StageError('Требуются выбранные проекты')
    roots=[]
    for project in projects:
        name=project['projectRoot'];safe(owner,name)
        if '.git' in name.split('/'):raise StageError('Служебный project root запрещён')
        roots.extend(name+'/'+p for p in ['student','reference','tests','rubric.md','contract.md'])
    if manifest.get('replacementRoots')!=roots:raise StageError('Недопустимые replacement roots')
    replacements={};seeds=[]
    for file in manifest.get('files',[]):
        name=file['target'];path=safe(core,name)
        if name in replacements or not any(name==r or name.startswith(r+'/') for r in roots):raise StageError('Core file вне replacement roots или collision')
        if not path.is_file() or digest(path.read_bytes())!=file['sha256']:raise StageError('Core bytes не совпадают с receipt')
        if file['origin'] in ('public','common'):
            original=Path(file['source'])
            if not original.is_relative_to(owner):raise StageError('Public source вне owner')
            safe(owner,original.relative_to(owner).as_posix())
            if not original.is_file() or digest(original.read_bytes())!=file['sha256']:raise StageError('Public input изменён после Core capture')
        elif file['origin']!='teacher':raise StageError('Неизвестный file origin')
        if '.git' in name.split('/'):
            if not any(name.startswith(p['projectRoot']+'/student/') for p in projects) or name.endswith('/commondir') or name.endswith('/alternates'):raise StageError('Недопустимый Git seed')
            seeds.append(book+'/'+name)
        replacements[name]=path.read_bytes()
    actual=inventory(core);expected={'materialization.json':digest(manifest_bytes),**{f['target']:f['sha256'] for f in manifest.get('files',[])}}
    if actual!=expected:raise StageError('Core output содержит неучтённые файлы')
    for name,sha in {**manifest.get('sourceDocuments',{}),**manifest.get('commonSources',{})}.items():
        if digest(safe(owner,name).read_bytes())!=sha:raise StageError('Captured owner document/common изменён')
    # Git object snapshot: no checkout hooks, symlinks or submodules are executed.
    source_files={}
    listing=subprocess.check_output(['git','ls-tree','-rz','--full-tree',commit],cwd=public)
    for item in listing.split(b'\0'):
        if not item:continue
        metadata,name=item.split(b'\t',1);mode,kind,oid=metadata.decode().split();name=name.decode();safe(public,name)
        if mode not in ('100644','100755') or kind!='blob':raise StageError('Public Git snapshot содержит symlink/submodule/special file')
        source_files[name]=(subprocess.check_output(['git','cat-file','blob',oid],cwd=public),mode)
    output.mkdir(mode=0o700)
    try:
        for name,(data,mode) in source_files.items():
            if any(name==book+'/'+r or name.startswith(book+'/'+r+'/') for r in roots):continue
            target=safe(output,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(int(mode[-3:],8))
        for name,data in replacements.items():
            target=safe(output,book+'/'+name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        runtime_roots=[book+'/_generated',book+'/.quarto','.quarto']
        if any(safe(output,name).exists() for name in runtime_roots):raise StageError('Runtime roots должны отсутствовать при freeze')
        git(output,'init','-q','--initial-branch=private-stage');files=inventory(output)
        # Nested educational .git cannot be indexed by Git. The receipt hashes it
        # in full; both pre/post build validation cover modified AND added files.
        for name in files:
            if '.git' in name.split('/'):continue
            oid=git(output,'hash-object','-w','--stdin',data=(output/name).read_bytes())
            mode='100755' if os.access(output/name,os.X_OK) else '100644'
            git(output,'update-index','--add','--cacheinfo',mode,oid,name)
        tree=git(output,'write-tree');env={**os.environ,'GIT_AUTHOR_NAME':'Private stage','GIT_AUTHOR_EMAIL':'stage@example.invalid','GIT_COMMITTER_NAME':'Private stage','GIT_COMMITTER_EMAIL':'stage@example.invalid'}
        stage_commit=git(output,'commit-tree',tree,data=b'Private materialized source\n',env=env);git(output,'update-ref','refs/heads/private-stage',stage_commit)
        value={'schema':'pl-private-source-v1','publicBase':{'repository':repository,'commit':commit,'book':book},'privateStage':{'path':str(output),'commit':stage_commit,'tree':tree,'remotes':[]},'materialization':{'sha256':digest(manifest_bytes),'declarationsHash':manifest['declarationsHash'],'files':manifest['files'],'commonSources':manifest.get('commonSources',{})},'seedFiles':seeds,'seedStorage':'receipt-hashed-outside-stage-index','runtimeRoots':runtime_roots,'files':files}
        receipt.parent.mkdir(parents=True,exist_ok=True)
        with receipt.open('x') as stream:json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n')
        receipt.chmod(0o600);validate(output,receipt)
        if git(public,'status','--porcelain','--untracked-files=all') or git(public,'rev-parse','HEAD')!=commit:raise StageError('Public source изменён')
        return value
    except Exception:
        shutil.rmtree(output);receipt.unlink(missing_ok=True);raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','book','materialized','output','receipt'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:prepare(Path(args.source),args.book,Path(args.materialized),Path(args.output),Path(args.receipt))
    except (StageError,OSError,KeyError,TypeError) as error:parser.exit(1,f'Private source rejected: {error}\n')
if __name__=='__main__':main()
