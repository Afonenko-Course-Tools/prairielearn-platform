#!/usr/bin/env python3
"""Ограниченная initial preparation JDK; runtime ничего не нормализует."""
import argparse
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat

BASE_IMAGE='ghcr.io/afonenko-course-tools/java25-grader@sha256:6052b077f7d5fabaedbd2deb829eed15e9911beafaf78f29c90083ff917b8c17'
SOURCE_HOME=Path('/usr/lib/jvm/java-25-openjdk-amd64')
DESTINATION=Path('/opt/native-jdk')
ADMISSION_SHA256='8338212fa46a417a14b4849b9f0d64c0cb8ad5785dfd5b48045b7e33457c20d3'
EXPECTED_JDK_SHA256='9e10b940ad531cc2dede147c2bdab76cbeb419b5c7a11b6bd8e97e0a878bfa8f'
OMISSION='lib/src.zip'
OMISSION_TARGET=b'../../openjdk-25/src.zip'

class PreparationError(Exception):
    """Отказ operator preparation; это не ошибка или оценка студента."""

@dataclass(frozen=True)
class _Policy:
    # Только trusted Python fixtures задают альтернативную filesystem boundary.
    # CLI не предоставляет ни этих параметров, ни ослабления production pins.
    owner_uid:int=0
    trusted_root:Path=Path('/')
    missing_target:Path=Path('/usr/lib/jvm/openjdk-25')
    proof_scope:str='pinned-base-operator-copy'

def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def _metadata(info):
    return {'uid':info.st_uid,'gid':info.st_gid,'mode':oct(stat.S_IMODE(info.st_mode)),'bytes':info.st_size,'nlink':info.st_nlink,'dev':info.st_dev,'inode':info.st_ino,'mtimeNs':info.st_mtime_ns,'ctimeNs':info.st_ctime_ns}

def _require(condition,message):
    if not condition:raise PreparationError(message)

def _name(name,root=False):
    _require(isinstance(name,str) and (name or root),'Empty logical path')
    _require(not name.startswith('/') and '\\' not in name and not any(ord(c)<32 or ord(c)==127 for c in name),'Unsafe logical path')
    _require(not name or all(part not in ('','.','..') for part in name.split('/')),'Unsafe logical path')

def _parents(path,policy):
    _require(path.is_absolute() and path.is_relative_to(policy.trusted_root),'Path outside trusted source boundary')
    for parent in (path.parent,*path.parents[1:]):
        if not parent.is_relative_to(policy.trusted_root):break
        info=parent.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid==policy.owner_uid and not info.st_mode&0o7022,'Unsafe physical parent')
        if parent==policy.trusted_root:break

def _regular(path,policy,single=False):
    _parents(path,policy)
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        before=os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_uid==policy.owner_uid and not before.st_mode&0o7022,'Unsafe regular member')
        _require(not single or before.st_nlink==1,'Hardlink in normalized copy')
        digest=hashlib.sha256()
        while chunk:=stream.read(1024*1024):digest.update(chunk)
        _require(_metadata(os.fstat(stream.fileno()))==_metadata(before),'Regular member changed while reading')
        _require(_metadata(path.lstat())==_metadata(before),'Regular member path changed while reading')
    return {'sha256':digest.hexdigest(),'bytes':before.st_size,'mode':oct(stat.S_IMODE(before.st_mode))},_metadata(before)

def _snapshot(source,policy):
    _require(source.is_absolute() and source.resolve(strict=True)==source and not source.is_symlink(),'Unsafe source root')
    logical={};files={};directories={};links={};omissions={}
    def visit(path,name,ancestors):
        _name(name,root=True);_require(name not in logical,'Duplicate logical path')
        origin=path.lstat();_require(origin.st_uid==policy.owner_uid,'Unsafe source owner')
        item={'lstat':_metadata(origin),'type':'symlink' if stat.S_ISLNK(origin.st_mode) else 'directory' if stat.S_ISDIR(origin.st_mode) else 'regular' if stat.S_ISREG(origin.st_mode) else 'special'};logical[name]=item
        if stat.S_ISLNK(origin.st_mode):
            raw=os.readlink(os.fsencode(path));item['readlink']={'text':os.fsdecode(raw),'hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()};links[name]=item
        if name==OMISSION:
            _parents(path,policy)
            _require(stat.S_ISLNK(origin.st_mode) and raw==OMISSION_TARGET,'Known omission type/readlink changed')
            try:path.resolve(strict=True)
            except OSError as error:_require(error.errno==errno.ENOENT and error.filename==str(policy.missing_target),'Known omission failure changed')
            else:raise PreparationError('Known omission became resolvable')
            item['strictResolve']={'errno':errno.ENOENT,'missingPath':str(policy.missing_target)};omissions[name]=item;return
        resolved=path.resolve(strict=True)
        _require(not any(resolved==p or p in resolved.parents for p in (Path('/proc'),Path('/sys'),Path('/dev'))),'Virtual JDK target')
        _parents(resolved,policy);target=resolved.stat()
        _require(target.st_uid==policy.owner_uid and not target.st_mode&0o7022,'Unsafe source target owner/mode')
        item['resolvedTarget']=str(resolved);item['targetStat']=_metadata(target)
        if stat.S_ISDIR(target.st_mode):
            identity=(target.st_dev,target.st_ino);_require(identity not in ancestors,'Source directory cycle')
            children=sorted(path.iterdir());item['members']=[child.name for child in children];directories[name]={'mode':oct(target.st_mode&0o755),'uid':policy.owner_uid}
            for child in children:visit(child,child.name if not name else name+'/'+child.name,ancestors|{identity})
        else:
            _require(stat.S_ISREG(target.st_mode),'Special source member')
            record,observed=_regular(resolved,policy);_require(observed==item['targetStat'],'Source target changed')
            item['sha256']=record['sha256'];files[name]={**record,'mode':oct(target.st_mode&0o755)}
    visit(source,'',set());_require(set(omissions)=={OMISSION},'Exact omission is missing')
    return {'logical':logical,'files':files,'directories':directories,'links':links,'omissions':omissions}

def _portable(snapshot):
    # Сохраняем все live metadata в receipt и сравниваем их до/после операции.
    # dev/inode/ctime создаются filesystem/container; не portable source pins.
    value=json.loads(json.dumps(snapshot))
    for item in value['logical'].values():
        for field in ('lstat','targetStat'):
            for name in ('dev','inode','ctimeNs'):item.get(field,{}).pop(name,None)
    # links/omissions дублируют logical rows в JSON, поэтому derive их заново.
    value['links']={name:value['logical'][name] for name in snapshot['links']}
    value['omissions']={name:value['logical'][name] for name in snapshot['omissions']}
    return value

def _admission(admitted,source,destination,policy):
    expected=admitted['expectedNormalizedJdk'];before=admitted['sourceBefore']
    _require(set(expected)=={'home','release','files'} and expected['home']==str(destination),'Invalid expected JDK object')
    _require(admitted['sourceHome']==str(source) and before==admitted['sourceAfter'],'Invalid source admission')
    _require(_digest(before)==admitted['sourceBeforeSha256']==admitted['sourceAfterSha256'],'Source admission hash mismatch')
    _require(_digest(expected)==admitted['expectedNormalizedJdkSha256'],'Expected JDK hash mismatch')
    _require(expected['files']==before['files'] and admitted['expectedNormalizedDirectories']==before['directories'],'Expected payload differs from admitted source')
    for name,record in expected['files'].items():
        _name(name);_require(record['sha256']==before['logical'][name]['sha256'],'Source payload hash differs from logical row')
    _require(set(before['omissions'])=={OMISSION} and OMISSION not in expected['files'],'Invalid omission admission')
    _require(before['omissions'][OMISSION]['readlink']['hex']==OMISSION_TARGET.hex(),'Invalid admitted omission target')
    return expected,before

def _copy_regular(source,target,expected,policy):
    _require(not os.path.lexists(target),'Copy file collision')
    with os.fdopen(os.open(source,os.O_RDONLY|os.O_NOFOLLOW),'rb') as input_stream:
        before=_metadata(os.fstat(input_stream.fileno()))
        _require(before['uid']==policy.owner_uid and not int(before['mode'],8)&0o7022,'Unsafe copy source')
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as output:
            identity=(os.fstat(output.fileno()).st_dev,os.fstat(output.fileno()).st_ino)
            shutil.copyfileobj(input_stream,output,1024*1024);output.flush()
            os.fchmod(output.fileno(),int(expected['mode'],8))
        copied=target.lstat();_require(stat.S_ISREG(copied.st_mode) and copied.st_nlink==1 and (copied.st_dev,copied.st_ino)==identity,'Unsafe copied file identity')
        actual,_=_regular(target,policy,single=True)
        _require(actual==expected,'copied payload differs from admitted bytes/mode')
        _require(_metadata(os.fstat(input_stream.fileno()))==before,'Source changed during copy')

def _normalized(destination,policy):
    files={};directories={};identities={}
    _parents(destination,policy)
    for path in [destination,*sorted(destination.rglob('*'))]:
        name=path.relative_to(destination).as_posix();name='' if name=='.' else name;_name(name,root=True)
        info=path.lstat();_require(info.st_uid==policy.owner_uid and not info.st_mode&0o7022,'Unsafe normalized owner/mode')
        _require(not stat.S_ISLNK(info.st_mode),'Symlink in normalized copy')
        identities[name]=_metadata(info)
        if stat.S_ISDIR(info.st_mode):directories[name]={'uid':policy.owner_uid,'mode':oct(stat.S_IMODE(info.st_mode))}
        else:
            _require(stat.S_ISREG(info.st_mode),'Special normalized member');files[name],observed=_regular(path,policy,single=True);_require(observed==identities[name],'Normalized member changed')
    _require(not os.path.lexists(destination/OMISSION),'Omitted source archive appeared in normalized tree')
    return {'files':files,'directories':directories,'identities':identities}

def _prepare(source,destination,admitted,policy=_Policy()):
    source=Path(source);destination=Path(destination)
    try:
        _require(os.geteuid()==policy.owner_uid,'Preparation supervisor UID mismatch')
        _require(not destination.is_relative_to(source) and not source.is_relative_to(destination),'Source/destination overlap')
        _parents(destination,policy);_require(not os.path.lexists(destination),'Destination must be fresh')
        expected,accepted_source=_admission(admitted,source,destination,policy)
        before=_snapshot(source,policy);_require(_portable(before)==_portable(accepted_source),'Source differs from admitted logical paths/links/bytes/metadata')
        destination.mkdir(mode=0o700)
        for name in sorted((name for name in before['directories'] if name),key=lambda name:(len(name.split('/')),name)):
            _name(name);(destination/name).mkdir(mode=0o700)
        for name,record in sorted(expected['files'].items()):
            path=(source/name).resolve(strict=True)
            _require(str(path)==before['logical'][name]['resolvedTarget'],'Source link retargeted before copy')
            _copy_regular(path,destination/name,record,policy)
        for name,record in sorted(before['directories'].items(),key=lambda item:len(item[0].split('/')),reverse=True):(destination/name).chmod(int(record['mode'],8))
        copied=_normalized(destination,policy)
        _require(copied['files']==expected['files'] and copied['directories']==admitted['expectedNormalizedDirectories'],'copied payload set/directories differ from admission')
        after=_snapshot(source,policy);_require(after==before,'Source paths/links/metadata/bytes changed during preparation')
        final=_normalized(destination,policy);_require(final==copied,'Normalized copy changed before freeze')
        _require((destination/'release').read_text()==expected['release'],'Copied release differs from admitted release')
        return {'schemaVersion':1,'kind':'native-jdk-normalization-v1','status':'copy-verified-awaiting-ROOT-admission','proofScope':policy.proof_scope,'baseImage':BASE_IMAGE,'sourceHome':str(source),'destination':str(destination),'sourceAdmissionCanonicalSha256':_digest(admitted),'sourceBefore':before,'sourceAfter':after,'sourceBeforeSha256':_digest(before),'sourceAfterSha256':_digest(after),'expectedNormalizedJdkSha256':_digest(expected),'normalizedFiles':copied['files'],'normalizedBefore':copied,'normalizedAfter':final,'excludedNonPayload':before['omissions'],'actualCopyCreated':True,'normalizedInstallationAdmission':False,'nativeImageProof':False,'executedJava':False,'executedGradle':False,'executedLandlock':False}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
        raise PreparationError('JDK preparation failed closed: '+str(error)) from error

def _validate_production_admission(data):
    _require(hashlib.sha256(data).hexdigest()==ADMISSION_SHA256,'Unadmitted production source inventory bytes')
    value=json.loads(data)
    _require(_digest(value['expectedNormalizedJdk'])==EXPECTED_JDK_SHA256,'Wrong production expected payload')
    _require(value['sourceHome']==str(SOURCE_HOME) and value['counts']=={'directories':88,'logical':405,'regularPayload':316,'symlinks':97,'unresolvedNonPayload':1},'Wrong production source membership')
    return value

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--admission',required=True,type=Path);parser.add_argument('--receipt',required=True,type=Path);args=parser.parse_args(argv)
    try:
        _require(os.geteuid()==0 and platform.system()=='Linux' and platform.machine() in ('x86_64','amd64'),'Production preparation requires Linux amd64 UID0')
        _require(args.receipt.is_absolute() and '..' not in args.receipt.parts and not any(args.receipt.is_relative_to(root) for root in (SOURCE_HOME,DESTINATION)),'Receipt must be outside source and normalized trees')
        admitted=_validate_production_admission(args.admission.read_bytes())
        _parents(args.receipt,_Policy());_require(not os.path.lexists(args.receipt),'Receipt must be fresh')
        result=_prepare(SOURCE_HOME,DESTINATION,admitted)
        result['sourceInventoryBytesSha256']=ADMISSION_SHA256
        with args.receipt.open('x',encoding='utf-8') as output:
            args.receipt.chmod(0o600);json.dump(result,output,sort_keys=True,ensure_ascii=False);output.write('\n')
        return 0
    except (PreparationError,OSError,ValueError,KeyError) as error:parser.exit(2,str(error)+'\n')

if __name__=='__main__':raise SystemExit(main())
