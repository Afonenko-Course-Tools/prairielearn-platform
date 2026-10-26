#!/usr/bin/env python3
"""Заморозить приватный source из публичного Git snapshot и точного Core receipt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

class StageError(Exception):
    pass

def digest(data):return hashlib.sha256(data).hexdigest()
def read(path):
    try:
        value=json.loads(path.read_bytes())
        if not isinstance(value,dict):raise StageError('Требуется объект staging receipt, не artifact files')
        return value
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

def physical_state(root):
    """Замкнутый live inventory, включая ignored файлы, но не служебный Git owner."""
    files={};directories={}
    def walk(path):
        for child in sorted(path.iterdir()):
            if path==root and child.name=='.git':continue
            before=child.lstat()
            if stat.S_ISDIR(before.st_mode):
                directories[child.relative_to(root).as_posix()]=directory_identity(before);walk(child)
                if directory_identity(child.lstat())!=directory_identity(before):raise StageError('Каталог source изменён во время чтения')
            elif stat.S_ISREG(before.st_mode) and before.st_nlink==1:
                data=child.read_bytes();after=child.lstat()
                identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
                if identity(before)!=identity(after):raise StageError('Live input изменён во время чтения')
                files[child.relative_to(root).as_posix()]=(digest(data),*identity(after))
            else:raise StageError('Source содержит ссылку или специальный файл')
    walk(root)
    return files,directories

def directory_identity(s):
    return (stat.S_IFMT(s.st_mode),stat.S_IMODE(s.st_mode),s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mtime_ns,s.st_ctime_ns)

def tree_entries(root,commit):
    entries={}
    for item in subprocess.check_output(['git','ls-tree','-rz','--full-tree',commit],cwd=root).split(b'\0'):
        if not item:continue
        metadata,name=item.split(b'\t',1);mode,kind,oid=metadata.decode().split();name=name.decode();safe(root,name)
        if mode not in ('100644','100755') or kind!='blob':raise StageError('Public Git snapshot содержит symlink/submodule/special file')
        entries[name]=(mode,oid)
    return entries

def check_checkout(root,commit,repository,entries,source_files):
    if git(root,'rev-parse','--show-toplevel')!=str(root) or (root/'.git').is_symlink() or not ((root/'.git').is_dir() or (root/'.git').is_file()):raise StageError('Требуется настоящий Git checkout')
    if git(root,'rev-parse','HEAD')!=commit or git(root,'remote','get-url','origin')!=repository or tree_entries(root,commit)!=entries:raise StageError('Origin/HEAD/tree execution не совпадает с public snapshot')
    index={}
    for item in git(root,'ls-files','--stage','-z').split('\0'):
        if not item:continue
        metadata,name=item.split('\t',1);mode,oid,level=metadata.split()
        if level!='0' or name in index:raise StageError('Неоднозначный Git index')
        index[name]=(mode,oid)
    if index!=entries:raise StageError('Git index отличается от HEAD')
    if any(item and not item.startswith('H ') for item in git(root,'ls-files','-v','-z').split('\0')):raise StageError('skip-worktree/assume-unchanged запрещены')
    for name,(data,mode) in source_files.items():
        path=safe(root,name)
        if not path.is_file() or path.is_symlink() or path.read_bytes()!=data or bool(path.stat().st_mode&0o111)!=(mode=='100755'):raise StageError('Tracked live bytes/type/mode отличаются от Git objects')

def exact_execution_inventory(execution,entries,generated):
    files,directories=physical_state(execution);allowed=set(entries)|set(generated)
    if set(files)!=allowed:raise StageError('Execution содержит неучтённые untracked/ignored файлы')
    parents=set()
    for name in allowed:
        parent=Path(name).parent
        while parent!=Path('.'):
            parents.add(parent.as_posix());parent=parent.parent
    git_roots=set()
    for name in generated:
        parts=name.split('/')
        if '.git' in parts:git_roots.add('/'.join(parts[:parts.index('.git')+1]))
    additional=set(directories)-parents;admitted=set()
    for root in git_roots:
        for tail in ('objects/info','objects/pack','refs/tags'):
            name=root+'/'+tail
            if name not in additional:continue
            path=safe(execution,name);before=path.lstat()
            if not stat.S_ISDIR(before.st_mode) or stat.S_IMODE(before.st_mode)!=0o755 or any(path.iterdir()):raise StageError('Некорректный пустой каталог Git seed')
            if directory_identity(before)!=directories[name] or directory_identity(path.lstat())!=directories[name]:raise StageError('Identity пустого каталога Git seed изменилась')
            admitted.add(name)
    if additional!=admitted:raise StageError('Execution содержит неучтённые каталоги')
    return files,directories

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

def publication_catalog_state(path):
    if path.resolve()!=path:raise StageError('Publication catalog: символические ссылки запрещены')
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise StageError('Publication catalog должен быть обычным файлом без hardlink')
    data=path.read_bytes();after=path.lstat()
    identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mode,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink)
    if identity(before)!=identity(after):raise StageError('Publication catalog изменён во время чтения')
    return data,identity(after)

def prepare(public,book,core,output,receipt,publication_catalog=None):
    public=Path(public).absolute();core=Path(core).absolute();output=Path(output).absolute();receipt=Path(receipt).absolute()
    for root in (public,core):
        if root.resolve()!=root or not root.is_dir():raise StageError('Требуется настоящий входной каталог')
    public_owner=safe(public,book)
    if output.exists() or receipt.exists() or output.is_symlink() or receipt.is_symlink():raise StageError('Output и receipt должны быть новыми')
    for root in (public,core):
        if output==root or output.is_relative_to(root) or root.is_relative_to(output):raise StageError('Output пересекается с source')
        if receipt==root or receipt.is_relative_to(root) or root.is_relative_to(receipt):raise StageError('Receipt пересекается с входным source/Core')
    if receipt.is_relative_to(output) or not output.parent.is_dir() or output.parent.resolve()!=output.parent or receipt.parent.resolve()!=receipt.parent:raise StageError('Receipt должен быть снаружи stage, родители — настоящими')
    if git(public,'status','--porcelain','--untracked-files=all'):raise StageError('Публичный source должен быть clean')
    repository=git(public,'remote','get-url','origin')
    if not re.fullmatch(r'https://[^/@\s]+/[^\s]+',repository):raise StageError('Origin должен быть credential-free HTTPS')
    commit=git(public,'rev-parse','HEAD');manifest_path=core/'materialization.json';manifest_bytes=manifest_path.read_bytes();manifest=read(manifest_path)
    if manifest.get('schema')!='course-project-materialization-v1' or manifest.get('audience')!='grading':raise StageError('Требуется grading Core receipt данного owner')
    if manifest.get('sourceCommit')!=commit:raise StageError('Core sourceCommit не совпадает с public HEAD')
    owner=Path(manifest['sourceRoot'])
    if str(owner)!=manifest['sourceRoot'] or not owner.is_absolute() or owner.resolve()!=owner or not owner.is_dir():raise StageError('Некорректный execution owner')
    execution=Path(git(owner,'rev-parse','--show-toplevel'))
    if execution.resolve()!=execution or owner!=safe(execution,book):raise StageError('Execution owner не равен Git root/book')
    distinct=execution!=public
    if distinct and any(not (root/'.git').is_dir() for root in (public,execution)):raise StageError('Раздельные источники должны быть самостоятельными Git checkout')
    if distinct and (execution.is_relative_to(public) or public.is_relative_to(execution)):raise StageError('Public/execution checkout пересекаются')
    if distinct and (core.is_relative_to(execution) or execution.is_relative_to(core)):raise StageError('Execution пересекается с Core output')
    for target in (output,receipt):
        if target==execution or target.is_relative_to(execution) or execution.is_relative_to(target):raise StageError('Output/receipt пересекается с execution source')
    entries=tree_entries(public,commit)
    source_files={name:(subprocess.check_output(['git','cat-file','blob',oid],cwd=public),mode) for name,(mode,oid) in entries.items()}
    check_checkout(public,commit,repository,entries,source_files)
    check_checkout(execution,commit,repository,entries,source_files)
    for name in entries:
        if stat.S_IMODE(safe(public,name).stat().st_mode)!=stat.S_IMODE(safe(execution,name).stat().st_mode):raise StageError('Public/execution tracked modes отличаются')
    projects=manifest.get('projects',[])
    if not projects or len({p['exerciseId'] for p in projects})!=len(projects):raise StageError('Требуются выбранные проекты')
    roots=[]
    for project in projects:
        name=project['projectRoot'];safe(owner,name)
        if '.git' in name.split('/'):raise StageError('Служебный project root запрещён')
        roots.extend(name+'/'+p for p in ['student','reference','tests','rubric.md','contract.md'])
    if manifest.get('replacementRoots')!=roots:raise StageError('Недопустимые replacement roots')
    replacements={};seeds=[];generated={}
    for file in manifest.get('files',[]):
        name=file['target'];path=safe(core,name)
        if name in replacements or not any(name==r or name.startswith(r+'/') for r in roots):raise StageError('Core file вне replacement roots или collision')
        if not path.is_file() or digest(path.read_bytes())!=file['sha256']:raise StageError('Core bytes не совпадают с receipt')
        if file['origin'] in ('public','common'):
            original=Path(file['source'])
            if not original.is_relative_to(owner):raise StageError('Public source вне owner')
            safe(owner,original.relative_to(owner).as_posix())
            if not original.is_file() or digest(original.read_bytes())!=file['sha256']:raise StageError('Public input изменён после Core capture')
            relative=original.relative_to(execution).as_posix()
            if relative in source_files:
                if digest(source_files[relative][0])!=file['sha256']:raise StageError('Public/common input отличается от Git blob')
            elif file['origin']=='public' and original.relative_to(owner).as_posix()==name and any(name.startswith(p['projectRoot']+'/student/') for p in projects):
                generated[relative]=file['sha256']
            else:raise StageError('Дополнительный public/common input вне точного student receipt')
        elif file['origin']!='teacher':raise StageError('Неизвестный file origin')
        if '.git' in name.split('/'):
            if not any(name.startswith(p['projectRoot']+'/student/') for p in projects) or name.endswith('/commondir') or name.endswith('/alternates'):raise StageError('Недопустимый Git seed')
            seeds.append(book+'/'+name)
        replacements[name]=path.read_bytes()
    actual=inventory(core);expected={'materialization.json':digest(manifest_bytes),**{f['target']:f['sha256'] for f in manifest.get('files',[])}}
    if actual!=expected:raise StageError('Core output содержит неучтённые файлы')
    for name,sha in [*manifest.get('sourceDocuments',{}).items(),*manifest.get('commonSources',{}).items()]:
        relative=book+'/'+name
        if relative not in source_files or digest(source_files[relative][0])!=sha or digest(safe(owner,name).read_bytes())!=sha or digest(safe(public_owner,name).read_bytes())!=sha:raise StageError('Captured owner document/common изменён или отсутствует в Git snapshot')
    catalog_target='_site-student/reference-catalog.json'
    catalog_state=None
    if publication_catalog is not None:
        publication_catalog=Path(publication_catalog).absolute()
        catalog_state=publication_catalog_state(publication_catalog)
        if any(name==catalog_target or name.startswith(catalog_target+'/') or catalog_target.startswith(name+'/') for name in entries):raise StageError('Publication catalog пересекается с public Git snapshot')
    execution_state=None
    if distinct:
        if set(physical_state(public)[0])!=set(entries):raise StageError('Чистый public snapshot содержит ignored дополнительные файлы')
        execution_state=exact_execution_inventory(execution,entries,generated)
    initial={root:physical_state(root) for root in {public,execution,core}}
    if distinct and initial[execution]!=execution_state:raise StageError('Execution изменён между проверкой и freeze')
    # Git objects берутся только из public; все replacement bytes — только из Core.
    output.mkdir(mode=0o700)
    try:
        for name,(data,mode) in source_files.items():
            if any(name==book+'/'+r or name.startswith(book+'/'+r+'/') for r in roots):continue
            target=safe(output,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(int(mode[-3:],8))
        for name,data in replacements.items():
            target=safe(output,book+'/'+name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        if catalog_state is not None:
            target=safe(output,catalog_target);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(catalog_state[0])
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
        if git(public,'status','--porcelain','--untracked-files=all'):raise StageError('Public source изменён')
        check_checkout(public,commit,repository,entries,source_files);check_checkout(execution,commit,repository,entries,source_files)
        if distinct and any(not (root/'.git').is_dir() for root in (public,execution)):raise StageError('Git topology раздельных источников изменилась')
        if distinct:exact_execution_inventory(execution,entries,generated)
        if any(physical_state(root)!=before for root,before in initial.items()):raise StageError('Public/execution/Core input изменён во время freeze')
        if catalog_state is not None and publication_catalog_state(publication_catalog)!=catalog_state:raise StageError('Publication catalog изменён во время freeze')
        return value
    except Exception:
        shutil.rmtree(output);receipt.unlink(missing_ok=True);raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','book','materialized','output','receipt'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--publication-catalog',type=Path,action='append',help='Один полный публикационный каталог для _site-student/reference-catalog.json')
    args=parser.parse_args()
    if args.publication_catalog and len(args.publication_catalog)!=1:parser.error('Допустим только один --publication-catalog')
    try:prepare(Path(args.source),args.book,Path(args.materialized),Path(args.output),Path(args.receipt),publication_catalog=args.publication_catalog[0] if args.publication_catalog else None)
    except (StageError,OSError,KeyError,TypeError) as error:parser.exit(1,f'Private source rejected: {error}\n')
if __name__=='__main__':main()
