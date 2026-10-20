#!/usr/bin/env python3
"""One explicit JDK25/official JUnit runner for host and /grade jobs."""
import argparse
import hashlib
import stat
import zipfile
import zlib
import shutil
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import selectors
import secrets
import signal
import subprocess
import sys
import tempfile
import time

OUTPUT_LIMIT = 65536


class GraderError(Exception):
    """An operator/configuration failure, never a wrong student answer."""


def _protect_input_identity(job):
    # Bind mounts retain host owners. chmod(0700) alone is ineffective when a
    # host owner has the same numeric UID as the official container's sbuser.
    # Remap only the container account; never chown the caller's mounted tree.
    import pwd
    owners={path.stat().st_uid for path in (job,job/'student',job/'tests')}
    if pwd.getpwnam('sbuser').pw_uid not in owners:return
    if not Path('/.dockerenv').is_file():
        raise GraderError('Sandbox UID remapping requires the supported Docker container')
    allocated={entry.pw_uid for entry in pwd.getpwall()}
    candidate=next((uid for uid in range(60000,60100) if uid not in owners|allocated),None)
    if candidate is None:raise GraderError('No isolated sandbox UID is available')
    code,text,reason=_run(['usermod','--uid',str(candidate),'sbuser'],job,5)
    if code or reason or pwd.getpwnam('sbuser').pw_uid in owners:
        raise GraderError('Cannot isolate sandbox UID from mounted input owners')


def _child_file_limit():
    # Denied /proc makes JDK jspawnhelper close descriptors up to the hard
    # limit. Bound that work before Landlock, without granting new filesystem
    # access or changing the host supervisor's limit.
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    hard=4096 if hard==resource.RLIM_INFINITY else min(hard,4096)
    soft=hard if soft==resource.RLIM_INFINITY else min(soft,hard)
    resource.setrlimit(resource.RLIMIT_NOFILE,(soft,hard))


def _run(command, cwd, timeout, output_limit=OUTPUT_LIMIT):
    try:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, preexec_fn=_child_file_limit,
            env={**os.environ,"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"},
        )
    except OSError as exc:
        raise GraderError("Required grading executable is unavailable") from exc
    output = bytearray()
    reason = None
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    room = output_limit - len(output)
                    output.extend(chunk[:room])
                    if len(chunk) > room:
                        reason = "output_limit"
                        break
                if reason:
                    break
            if reason is None:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
    finally:
        # Clean up children too, including processes retaining a stdout handle.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
    text = bytes(output).decode("utf-8", errors="replace")
    text = text.encode("utf-8")[:output_limit].decode("utf-8", errors="ignore")
    return process.returncode, text, reason


def _names(config, key):
    names = config.get(key)
    if not isinstance(names, list) or not names or len(names) > 64:
        raise GraderError("Source and test file lists must be nonempty")
    for name in names:
        if not isinstance(name, str) or len(name) > 512:
            raise GraderError("Invalid Java file name")
        parts = PurePosixPath(name).parts
        if (not parts or PurePosixPath(name).is_absolute() or "\\" in name
                or any(part in (".", "..") or part.startswith(".") for part in parts)
                or "/".join(parts) != name or not name.endswith(".java")):
            raise GraderError("Invalid Java file path")
    if len(set(names)) != len(names):
        raise GraderError("Duplicate Java file")
    return names


def _files(root, names):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Missing source directory")
    files = []
    for name in names:
        path = root
        for part in PurePosixPath(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("Symlink source is forbidden")
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("Missing or oversized Java file")
        files.append(str(path.resolve()))
    return files


PLATFORM=Path(__file__).resolve().parents[2]

def preflight(runtime):
    try:
        registry=json.loads((PLATFORM/'runtime-profiles.json').read_text())
        profile=registry['profiles'][runtime]
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=profile['runnerSha256']:raise GraderError('Runtime runner checksum mismatch')
        bundle=PLATFORM/profile['bundle']
        actual={p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
        if actual!=set(profile['files']):raise GraderError('Runtime bundle contains unregistered or missing files')
        for name,digest in profile['files'].items():
            files=_files_any(bundle,name)
            if hashlib.sha256(files.read_bytes()).hexdigest()!=digest:
                raise GraderError('Runtime bundle checksum mismatch: '+name)
        for name,sha in profile['sharedFiles'].items():
            if hashlib.sha256(_files_any(PLATFORM,name).read_bytes()).hexdigest()!=sha:raise GraderError('Shared runtime checksum mismatch')
        code,output,reason=_run(['java','-version'],PLATFORM,5)
        if code or reason or not re.search(r'version "25(?:[.\"+\-])',output):
            raise GraderError('The grader requires an actual JDK 25 runtime')
        compiler_code,compiler_output,compiler_reason=_run(['java','-XX:TieredStopAtLevel=1','com.sun.tools.javac.Main','-version'],PLATFORM,5)
        if compiler_code or compiler_reason or not re.search(r'javac 25(?:[.\s+\-]|$)',compiler_output):
            raise GraderError('The grader requires the actual JDK25 compiler')
        return profile,bundle,output.strip()
    except (KeyError,OSError,ValueError) as error:
        raise GraderError('Missing or invalid versioned runtime bundle') from error

def _files_any(root,name):
    p=PurePosixPath(name)
    if p.is_absolute() or '\\' in name or not p.parts or any(x in ('.','..') for x in name.split('/')):
        raise GraderError('Unsafe runtime path')
    current=root
    if current.is_symlink():raise GraderError('Symlink runtime bundle')
    for part in p.parts:
        current=current/part
        if current.is_symlink():raise GraderError('Symlink runtime file')
    if not current.is_file():raise GraderError('Missing runtime file')
    return current

def _compiled_class_names(root):
    # javac writes actual binary names into this fresh private output directory.
    # Enumerating paths neither loads classes nor runs static initializers.
    return {'.'.join(path.relative_to(root).with_suffix('').parts)
            for path in root.rglob('*.class')}

def _source_classes(files):
    names=[]
    for f in files:
        text=Path(f).read_text(encoding='utf-8')
        package=re.search(r'^\s*package\s+([\w.]+)\s*;',text,re.M)
        names.append((package[1]+'.' if package else '')+Path(f).stem)
    return names

def _invalid(message,output='',classification='student-compilation-failure'):
    return {'gradable':False,'format_errors':message,'output':output,'classification':classification,'studentCompilation':'failure','trustedCompilation':'not-run','infrastructure':'complete'}

def _score(raw,counts,policy):
    mode=policy.get('mode')
    if mode=='weighted':return raw['score']
    if mode=='all-pass':return float(counts['failed']==0 and counts['aborted']==0 and counts['skipped']==0 and counts['executed']>0)
    outcomes=counts['outcomes']
    if mode=='contract-groups':
        groups=policy['groups'];total=sum(g['weight'] for g in groups)
        if total<=0:raise GraderError('Scoring groups require positive total weight')
        if any(t not in outcomes for g in groups for t in g['tests']):raise GraderError('Scoring group references missing stable test ID')
        return sum(g['weight'] for g in groups if all(outcomes[t]=='successful' for t in g['tests']))/total
    if mode=='threshold':
        value=raw['score'] if policy['basis']=='score' else counts['passed']
        return float(value>=policy['value'])
    raise GraderError('Unknown scoring policy')

def validate_config(config):
    allowed={'schemaVersion','sourceFiles','testFiles','mode','runtime','java','limits','scoring','discovery','variants','apiPrecheck','additionalJavaSources','publicCases','feedback'}
    if not isinstance(config,dict) or set(config)-allowed or config.get('schemaVersion')!=1:
        raise GraderError('Expected closed schemaVersion1 JUnit grading descriptor')
    if config.get('mode') not in ('implementation','student-tests'):raise GraderError('Invalid submission mode')
    if 'apiPrecheck' in config:
        api=config['apiPrecheck']
        if (config['mode']!='implementation' or not isinstance(api,dict) or set(api)!={'files','entry'}
                or not isinstance(api['entry'],str) or not re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*',api['entry'])):
            raise GraderError('Invalid Java API precheck')
        names=_names(api,'files');tests=_names(config,'testFiles')
        if not set(names)<set(tests):raise GraderError('API precheck files must be a proper subset of trusted tests')
    if 'additionalJavaSources' in config:
        policy=config['additionalJavaSources']
        caps={'maxFiles':128,'maxFileBytes':1048576,'maxTotalBytes':4194304,'maxArchiveBytes':2097152}
        if (config.get('runtime')!='java25-junit-v1' or config['mode']!='implementation'
                or not isinstance(policy,dict) or set(policy)!={'archive',*caps}
                or not isinstance(policy['archive'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.zip',policy['archive'])
                or any(type(policy[k]) is not int or not 1<=policy[k]<=limit for k,limit in caps.items())):
            raise GraderError('Invalid closed additional Java sources policy')
        reserved=[*_names(config,'sourceFiles'),*_names(config,'testFiles'),'grading-job.json','tests/grading-job.json']
        if any(_path_collision(policy['archive'],name) for name in reserved):
            raise GraderError('Additional Java archive conflicts with a declared/private path')
    java=config.get('java',{})
    if set(java)-{'release','encoding','compiler-options'} or java.get('release')!=25 or java.get('encoding')!='UTF-8':raise GraderError('Java25 UTF-8 is required')
    opts=java.get('compiler-options',[])
    if opts!=['-proc:none','-Xmaxerrs','5']:raise GraderError('Unsupported compiler options; annotation processing is forbidden')
    limits=config.get('limits',{})
    if set(limits)-{'outer-seconds','compile-seconds','run-seconds','max-output-bytes','networking'} or limits.get('networking') is not False:raise GraderError('Invalid offline limits')
    for name,default in [('outer-seconds',30),('compile-seconds',15),('run-seconds',10),('max-output-bytes',65536)]:
        value=limits.get(name,default)
        if type(value) not in (int,float) or value<=0:raise GraderError('Limits must be positive numbers')
    if limits.get('compile-seconds',15)>limits.get('outer-seconds',30) or limits.get('run-seconds',10)>limits.get('outer-seconds',30):raise GraderError('Inner limit exceeds outer limit')
    if type(limits.get('max-output-bytes',65536)) is not int or limits.get('max-output-bytes',65536)>65536:raise GraderError('Maximum output limit is 65536')
    scoring=config.get('scoring',{})
    mode=scoring.get('mode')
    fields={'weighted':{'mode'},'all-pass':{'mode'},'contract-groups':{'mode','groups'},'threshold':{'mode','basis','value'}}
    if mode not in fields or set(scoring)!=fields[mode]:raise GraderError('Invalid closed scoring policy')
    if mode=='threshold' and (scoring['basis'] not in ('score','passed-tests') or type(scoring['value']) not in (int,float) or scoring['value']<0):raise GraderError('Invalid threshold')
    if mode=='contract-groups':
        if not isinstance(scoring['groups'],list) or not scoring['groups']:raise GraderError('Missing groups')
        ids=set()
        for g in scoring['groups']:
            if set(g)!={'id','weight','tests'} or g['id'] in ids or type(g['weight']) not in (int,float) or g['weight']<=0 or not isinstance(g['tests'],list) or not g['tests'] or any(not isinstance(x,str) for x in g['tests']):raise GraderError('Invalid scoring group')
            ids.add(g['id'])
    discovery=config.get('discovery',{})
    if set(discovery)!={'min-executed','allow-skipped'} or type(discovery['min-executed']) is not int or discovery['min-executed']<1 or type(discovery['allow-skipped']) is not bool:raise GraderError('Invalid discovery policy')

# These affect only the compiler JVM, not Java source semantics or allowed author options.
COMPILER_JVM=['java','-XX:TieredStopAtLevel=1','-XX:ActiveProcessorCount=2']
COMPILER=['com.sun.tools.javac.Main','--release','25','-encoding','UTF-8','-proc:none','-Xmaxerrs','5','-sourcepath','']

class _JobRuntime:
    """Immutable libraries/official adapter compiled once, private to one job."""
    def __init__(self,root,bundle):
        self.root=root;self.bundle=bundle;self.adapter=root/'adapter';self.library_dir=root/'libs'
        self.adapter.mkdir();self.library_dir.mkdir();self.compiled=False
        self.compiler_archive=root/'compiler.jsa'
        for jar in bundle.glob('*.jar'):shutil.copyfile(jar,self.library_dir/jar.name)
        self.libs=os.pathsep.join(sorted(str(x) for x in self.library_dir.glob('*.jar')))
    def compiler(self):
        # Only JDK javac classes are loaded: submitted code is parsed, never
        # executed (-proc:none). Generate cold within this job, never import an
        # author archive or reuse it across jobs/Java versions.
        option='SharedArchiveFile' if self.compiler_archive.is_file() else 'ArchiveClassesAtExit'
        return [*COMPILER_JVM,'-XX:'+option+'='+str(self.compiler_archive),*COMPILER]
    def protect_archive(self):
        if self.compiler_archive.is_file():self.compiler_archive.chmod(0o600)
    def ensure_adapter(self,job,limits,durations,diagnostics):
        if self.compiled:
            durations['runnerCompilation']=0.0
            return
        files=[str(self.bundle/'PlatformJUnitAdapter.java'),str(self.bundle/'PlatformApiPrecheck.java'),*map(str,(self.bundle/'upstream').rglob('*.java'))]
        start=time.monotonic()
        code,text,reason=_run([*self.compiler(),'-cp',self.libs,'-d',str(self.adapter),*files],job,limits.get('compile-seconds',15),int(limits['max-output-bytes']))
        self.protect_archive()
        durations['runnerCompilation']=time.monotonic()-start
        diagnostics['runnerCompilation']=text.replace(str(job),'/grade').replace(str(self.root),'/runtime')
        if code or reason:raise GraderError('Official JUnit adapter compilation failed: '+diagnostics['runnerCompilation'])
        self.compiled=True
        if os.environ.get('PL_CONTAINMENT')=='official':
            self.root.chmod(0o711)
            for directory in (self.adapter,self.library_dir):
                directory.chmod(0o755)
                for file in directory.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)


def _api_precheck(job,config,stage,student,files,runtime,limits,durations,diagnostics):
    """Trusted Java API code executes with the same official containment as JUnit."""
    runtime.ensure_adapter(job,limits,durations,diagnostics)
    compiled=stage/'precheck';compiled.mkdir()
    start=time.monotonic()
    code,text,reason=_run([*runtime.compiler(),'-cp',os.pathsep.join([runtime.libs,str(runtime.adapter)]),'-d',str(compiled),*files],job,limits.get('compile-seconds',15),int(limits['max-output-bytes']))
    runtime.protect_archive();durations['apiCompilation']=time.monotonic()-start;diagnostics['apiCompilation']=text.replace(str(job),'/grade').replace(str(stage),'/scratch')
    if code or reason:raise GraderError('API precheck compilation failed: '+(reason or diagnostics['apiCompilation']))
    if _compiled_class_names(student)&_compiled_class_names(compiled):
        return {'status':'unsafe','message':'Классы решения конфликтуют с доверенными API-классами'},compiled,None
    output=stage/'api-results';output.mkdir();scratch=stage/'api-scratch';scratch.mkdir();params=stage/'api-params';params.mkdir()
    signature=secrets.token_hex(32);result_file=output/(secrets.token_hex(32)+'.json');parameter_file=params/'params.json'
    parameter_file.write_text(json.dumps({'classes':str(student),'scratch':str(scratch),'entry':config['entry'],'signature':signature,'result_file':str(result_file)}))
    prefix=[];containment='host-diagnostic'
    if os.environ.get('PL_CONTAINMENT')=='official':
        if os.geteuid()!=0 or not Path('/usr/local/bin/landlock_sandbox').is_file() or not shutil.which('runuser'):raise GraderError('Official API precheck containment prerequisites missing')
        _protect_input_identity(job);stage.chmod(0o711)
        for directory in (student,compiled,runtime.adapter,runtime.library_dir):
            directory.chmod(0o755)
            for file in directory.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)
        for directory in (output,scratch,params):directory.chmod(0o777)
        parameter_file.chmod(0o644);job.chmod(0o711)
        for folder in ('student','tests'):(job/folder).chmod(0o700)
        prefix=['runuser','-u','sbuser','--','/usr/local/bin/landlock_sandbox'];containment='official-landlock-sbuser'
    classpath=os.pathsep.join([str(runtime.adapter),runtime.libs,str(compiled)])
    start=time.monotonic()
    code,text,reason=_run([*prefix,'java','-Xmx128m','-XX:TieredStopAtLevel=1','-XX:ActiveProcessorCount=2','-XX:-UsePerfData','-XX:+DisableAttachMechanism','--illegal-native-access=deny','-cp',classpath,'org.prairielearn.api.PlatformApiPrecheck',str(parameter_file)],scratch,limits.get('run-seconds',10),int(limits['max-output-bytes']))
    durations['apiExecution']=time.monotonic()-start;diagnostics['apiExecution']=text.replace(str(stage),'/scratch')
    if code or reason:raise GraderError('API precheck execution failed: '+(reason or str(code)))
    try:
        value=json.loads(result_file.read_text())
        if value.pop('signature')!=signature or value.get('status') not in ('success','mismatch','infrastructure'):raise ValueError('Invalid API report')
    except (OSError,ValueError,KeyError) as error:raise GraderError('API precheck report missing or invalid') from error
    if value['status']=='infrastructure':raise GraderError('API precheck infrastructure failure: '+value.get('message',''))
    return value,compiled,containment

def _execute(job,config,sources,tests,bundle,toolchain,runtime,student_tests=False):
    if student_tests!=(config['mode']=='student-tests'):raise GraderError('Private execution mode differs from validated submission mode')
    limits=config['limits'];durations={};diagnostics={}
    with tempfile.TemporaryDirectory(prefix='java25-junit-') as tmp:
        stage=Path(tmp);student=stage/'student';trusted=stage/'trusted'
        for d in (student,trusted):d.mkdir()
        adapter=runtime.adapter;library_dir=runtime.library_dir;libs=runtime.libs
        def compile_phase(name,files,output,classpath):
            start=time.monotonic();code,text,reason=_run([*runtime.compiler(),'-cp',classpath,'-d',str(output),*files],job,limits.get('compile-seconds',15),int(limits['max-output-bytes']))
            runtime.protect_archive()
            durations[name]=time.monotonic()-start;diagnostics[name]=text.replace(str(job),'/grade').replace(str(stage),'/scratch')
            return code,reason
        def unsafe(message):
            value=_invalid(message,classification='unsafe-submission')
            value.update(studentCompilation='success',trustedCompilation='success' if 'trustedCompilation' in durations else 'not-run',dependentExecution='not-run',durations=durations,diagnostics=diagnostics,toolchain=toolchain)
            if 'apiPrecheck' in config:
                value['apiPrecheck']='success' if 'apiExecution' in durations else 'not-run'
                if 'apiExecution' in durations:value['apiContainment']=api_containment
            return value
        reserved=('org.junit.','org.prairielearn.','org.json.','java.','javax.','PlatformJUnitAdapter','JUnitAutograder')
        if student_tests:
            code,reason=compile_phase('trustedCompilation',tests,trusted,libs)
            if code or reason:raise GraderError('Trusted fixture compilation failed: '+diagnostics['trustedCompilation'])
            code,reason=compile_phase('studentCompilation',sources,student,os.pathsep.join([libs,str(trusted)]))
        else:
            code,reason=compile_phase('studentCompilation',sources,student,libs)
        if reason:raise GraderError('Student compilation infrastructure limit: '+reason)
        if code:
            value=_invalid('Your submission could not be compiled',diagnostics['studentCompilation'])
            value.update(trustedCompilation='success' if student_tests else 'not-run',durations=durations,diagnostics=diagnostics,toolchain=toolchain)
            if 'apiPrecheck' in config:value.update(apiPrecheck='not-run',dependentExecution='not-run')
            return value
        if any(name.startswith(reserved) for name in _compiled_class_names(student)):
            return unsafe('Submitted classes collide with trusted namespaces')
        api_classes=None;api_containment=None
        if 'apiPrecheck' in config:
            selected=set(config['apiPrecheck']['files']);api_files=[f for f in tests if Path(f).relative_to(job/'tests').as_posix() in selected]
            value,api_classes,api_containment=_api_precheck(job,config['apiPrecheck'],stage,student,api_files,runtime,limits,durations,diagnostics)
            if value['status']=='unsafe':return unsafe(value['message'])
            if value['status']=='mismatch':
                return {'gradable':False,'classification':'student-api-mismatch','studentCompilation':'success','trustedCompilation':'not-run','apiPrecheck':'failure','dependentExecution':'not-run','infrastructure':'complete','apiDiagnostic':{'expected':value['expected'],'observed':value['observed']},'message':value['message']+'. Зависимые unit-тесты не выполнены.','durations':durations,'diagnostics':diagnostics,'toolchain':toolchain,'apiContainment':api_containment}
            tests=[f for f in tests if f not in api_files]
        if not student_tests:
            code,reason=compile_phase('trustedCompilation',tests,trusted,os.pathsep.join([libs,str(student),*([str(api_classes),str(runtime.adapter)] if api_classes else [])]))
            if reason:raise GraderError('Trusted suite compilation infrastructure limit: '+reason)
            if code:
                # Preserve established phase fields for private operator diagnosis.
                # Native callers still pass through student_result in main().
                return {'gradable':False,'grading_error':True,'classification':'infrastructure-failure','infrastructure':'failure','studentCompilation':'success','trustedCompilation':'failure','dependentExecution':'not-run','durations':durations,'diagnostics':diagnostics,'toolchain':toolchain,'message':'Trusted suite compilation failed'}
        trusted_names=_compiled_class_names(trusted)
        if api_classes is not None:trusted_names|=_compiled_class_names(api_classes)
        if _compiled_class_names(student)&trusted_names:return unsafe('Submitted classes collide with trusted classes')
        if api_classes is None:runtime.ensure_adapter(job,limits,durations,diagnostics)
        reports=stage/'results';reports.mkdir()
        params=stage/'params';params.mkdir()
        rawfile=reports/(secrets.token_hex(32)+'.json');countfile=reports/(secrets.token_hex(32)+'.json');signature=secrets.token_hex(32)
        parameter_file=params/'params.json'
        parameter_file.write_text(json.dumps({'results_file':str(rawfile),'counts_file':str(countfile),'signature':signature,'test_classes':_source_classes(sources if student_tests else tests),'student_classes':sorted(_compiled_class_names(student)),'student_classes_root':str(student.resolve()),'submission_mode':config['mode'],'public_cases':config.get('publicCases',[]),**({'trusted_console_support_root':str(trusted.resolve())} if 'coursesupport.JavaProcess' in trusted_names else {})}))
        containment='host-diagnostic'
        prefix=[]
        if os.environ.get('PL_CONTAINMENT')=='official':
            if os.geteuid()!=0 or not Path('/usr/local/bin/landlock_sandbox').is_file() or not shutil.which('runuser'):raise GraderError('Official root supervisor/sbuser/Landlock prerequisites missing')
            _protect_input_identity(job)
            # Preserve official UNIX boundaries: tests, source and runtime remain
            # private; compiled classpath is root-owned and only readable.
            stage.chmod(0o711);reports.chmod(0o777);params.chmod(0o777)
            for directory in (student,trusted,adapter,library_dir):
                directory.chmod(0o755)
                for file in directory.rglob('*'):file.chmod(0o755 if file.is_dir() else 0o644)
            parameter_file.chmod(0o644)
            job.chmod(0o711)
            for folder in ('student','tests'):(job/folder).chmod(0o700)
            prefix=['runuser','-u','sbuser','--','/usr/local/bin/landlock_sandbox']
            containment='official-landlock-sbuser'
        classpath=os.pathsep.join([str(adapter),libs,str(trusted),*([str(api_classes)] if api_classes else []),str(student)])
        command=[*prefix,'java','-Xmx128m','-XX:TieredStopAtLevel=1','-XX:ActiveProcessorCount=2','-XX:-UsePerfData','-XX:+DisableAttachMechanism','--illegal-native-access=deny','-cp',classpath,'PlatformJUnitAdapter',str(parameter_file)]
        start=time.monotonic();code,text,reason=_run(command,job,limits.get('run-seconds',10),int(limits['max-output-bytes']));durations['execution']=time.monotonic()-start
        base={'gradable':True,'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','durations':durations,'diagnostics':diagnostics,'toolchain':toolchain,'containment':containment,'scoring':config['scoring'],'output':text}
        if api_classes is not None:base.update(apiPrecheck='success',dependentExecution='complete',apiContainment=api_containment)
        if reason:
            base.update(score=0,classification='student-timeout' if reason=='timeout' else 'student-output-overflow',timed_out=reason=='timeout',output_limited=reason=='output_limit')
            base['message']=(f"Your code exceeded the execution time limit of {limits.get('run-seconds',10):g} seconds." if reason=='timeout' else f"Your code exceeded the output limit of {int(limits['max-output-bytes'])} bytes.")
            return base
        if code!=0 or not rawfile.is_file() or not countfile.is_file():raise GraderError('JUnit execution did not produce complete reports')
        try:
            raw=json.loads(rawfile.read_text());counts=json.loads(countfile.read_text())
            if raw.pop('signature')!=signature or counts.pop('signature')!=signature:raise ValueError('signature')
        except (KeyError,ValueError,OSError) as error:raise GraderError('Invalid JUnit report') from error
        # Internal observations remain available to private verification; main()
        # applies the student boundary before writing native RESULTS.
        if 'infrastructure' in counts.get('failureKinds',{}).values():raise GraderError('Trusted check raised an unexpected exception outside student code')
        base.update(publicCaseObservations=counts.get('publicCaseObservations',[]),rawResult=raw,counts=counts,maxPoints=raw['max_points'],tests=raw['tests'],message=raw.get('message',''))
        incomplete=counts['executed']<config['discovery']['min-executed'] or counts['discovered']==0 or counts['aborted']>0 or counts['containerFailures']>0 or (counts['skipped']>0 and not config['discovery']['allow-skipped'])
        if incomplete or not raw.get('gradable'):
            if not student_tests:raise GraderError('Trusted JUnit discovery/execution is incomplete')
            base.update(score=0,classification='student-test-quality-failure');return base
        kinds=set(counts.get('failureKinds',{}).values())
        if counts['failed'] and ('timeout' in kinds or 'output-limit' in kinds):
            timed_out='timeout' in kinds
            base.update(score=0,classification='student-timeout' if timed_out else 'student-output-overflow',timed_out=timed_out,output_limited=not timed_out)
        else:base.update(score=_score(raw,counts,config['scoring']),classification=('student-runtime-failure' if 'runtime' in kinds else 'behavior-failure') if counts['failed'] else 'success')
        return base

def _path_collision(left,right):
    return left==right or left.startswith(right+'/') or right.startswith(left+'/')


class _AdditionalSubmissionError(Exception):
    def __init__(self,message,classification='unsafe-submission'):
        self.classification=classification
        super().__init__('ZIP дополнительных Java sources: '+message+'. Исправьте доставку или используйте ручную сдачу.')


def _additional_inventory(job,config):
    """Fully validate bounded bytes before creating any extracted source file."""
    policy=config.get('additionalJavaSources')
    if policy is None:return [],None
    root=job/'student';file=root/policy['archive']
    if root.is_symlink() or not root.is_dir():raise _AdditionalSubmissionError('небезопасный каталог student')
    if not file.exists() and not file.is_symlink():return [],None
    if file.is_symlink() or not stat.S_ISREG(file.stat(follow_symlinks=False).st_mode):
        raise _AdditionalSubmissionError('архив должен быть обычным файлом без symlink')
    if file.stat().st_size>policy['maxArchiveBytes']:raise _AdditionalSubmissionError('превышен maxArchiveBytes')
    reserved=[*config['sourceFiles'],*config['testFiles'],'grading-job.json','tests/grading-job.json',policy['archive']]
    members=[];names={};total=0
    try:
        with file.open('rb') as raw:
            archive_bytes=raw.read(policy['maxArchiveBytes']+1)
        if len(archive_bytes)>policy['maxArchiveBytes']:raise _AdditionalSubmissionError('превышен maxArchiveBytes')
        import io
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries=archive.infolist()
            if len(entries)>256:raise _AdditionalSubmissionError('больше 256 записей ZIP')
            for info in entries:
                original=info.orig_filename
                directory=original.endswith('/')
                name=original[:-1] if directory else original
                parts=name.split('/')
                if (original!=info.filename or not name or '\\' in name or name.startswith('/')
                        or re.match(r'^[A-Za-z]:',name) or any(not part or part in ('.','..') or part.startswith('.') for part in parts)
                        or any(ord(c)<32 or ord(c)==127 for c in name) or len(parts)>32 or len(name.encode('utf-8'))>512):
                    raise _AdditionalSubmissionError('недопустимый относительный путь '+repr(original))
                mode=stat.S_IFMT(info.external_attr>>16)
                if info.flag_bits&1 or info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
                    raise _AdditionalSubmissionError('encrypted/неподдерживаемая запись '+repr(name))
                if mode not in (0,stat.S_IFDIR if directory else stat.S_IFREG):
                    raise _AdditionalSubmissionError('symlink/специальный тип записи '+repr(name))
                if name in names:raise _AdditionalSubmissionError('повтор пути '+repr(name))
                if any(_path_collision(name,x) and not (isdir and name.startswith(x+'/')) and not (directory and x.startswith(name+'/')) for x,isdir in names.items()):
                    raise _AdditionalSubmissionError('конфликт file/directory путей '+repr(name))
                if any(_path_collision(name,x) and not (directory and x.startswith(name+'/')) for x in reserved):raise _AdditionalSubmissionError('конфликт с основным/доверенным путём '+repr(name))
                names[name]=directory
                if directory:
                    if info.file_size:raise _AdditionalSubmissionError('каталог с содержимым '+repr(name))
                    continue
                if not name.endswith('.java'):raise _AdditionalSubmissionError('разрешены только .java: '+repr(name))
                if len(members)>=policy['maxFiles'] or info.file_size>policy['maxFileBytes'] or total+info.file_size>policy['maxTotalBytes']:
                    raise _AdditionalSubmissionError('превышен лимит количества/размера исходников')
                data=bytearray()
                with archive.open(info) as member:
                    while chunk:=member.read(min(65536,policy['maxFileBytes']-len(data)+1)):
                        data.extend(chunk)
                        if len(data)>policy['maxFileBytes'] or total+len(data)>policy['maxTotalBytes']:
                            raise _AdditionalSubmissionError('превышен фактический лимит bytes')
                if len(data)!=info.file_size:raise _AdditionalSubmissionError('размер записи не совпадает '+repr(name))
                try:bytes(data).decode('utf-8')
                except UnicodeError as error:raise _AdditionalSubmissionError('исходник не UTF-8: '+repr(name),'student-compilation-failure') from error
                total+=len(data);members.append((name,bytes(data)))
    except (zipfile.BadZipFile,zipfile.LargeZipFile,UnicodeError,zlib.error,NotImplementedError,RuntimeError,ValueError,OSError) as error:
        raise _AdditionalSubmissionError('повреждённый или неподдерживаемый архив ('+type(error).__name__+')') from error
    members.sort()
    return members,{'archive':policy['archive'],'archiveSha256':hashlib.sha256(archive_bytes).hexdigest(),'files':[{'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in members]}


def grade(job_dir):
    job=Path(job_dir).absolute()
    try:config=json.loads(_files_any(job,'tests/grading-job.json').read_text())
    except (OSError,ValueError) as error:raise GraderError('Missing or invalid grading configuration') from error
    validate_config(config);profile,bundle,toolchain=preflight(config['runtime'])
    import runpy
    try:runpy.run_path(str(PLATFORM/'runtime/student_feedback.py'))['validate_public_cases'](config.get('publicCases',[]))
    except ValueError as error:raise GraderError('Invalid public feedback policy') from error
    closure={**profile['files'],**profile['sharedFiles'],'runner/grade.py':profile['runnerSha256']}
    evidence={'dependencyHashes':closure,'dependencyHash':hashlib.sha256(json.dumps(closure,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
    additional_evidence=None
    def finish(value):
        if additional_evidence is not None:value['additionalSources']=additional_evidence
        value['executionEvidence']=evidence
        return value
    if profile['mode']!=config['mode']:raise GraderError('Runtime mode mismatch')
    source_names=_names(config,'sourceFiles');test_names=_names(config,'testFiles')
    try:tests=_files(job/'tests',test_names)
    except ValueError as error:raise GraderError('Missing or unsafe trusted sources') from error
    try:sources=_files(job/'student',source_names)
    except ValueError:return finish(_invalid('Upload all declared Java files'))
    try:additional,additional_evidence=_additional_inventory(job,config)
    except _AdditionalSubmissionError as error:
        result=_invalid(str(error),classification=error.classification)
        if 'apiPrecheck' in config:result.update(apiPrecheck='not-run',dependentExecution='not-run')
        return finish(result)
    with tempfile.TemporaryDirectory(prefix='java25-job-runtime-') as runtime_dir:
        extra_root=Path(runtime_dir)/'additional-sources'
        if additional:extra_root.mkdir(mode=0o700)
        for name,data in additional:
            target=extra_root/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with target.open('xb') as output:
                target.chmod(0o600);output.write(data)
            sources.append(str(target))
        runtime=_JobRuntime(Path(runtime_dir),bundle)
        if config['mode']=='implementation':return finish(_execute(job,config,sources,tests,bundle,toolchain,runtime))
        variants=config.get('variants')
        if not isinstance(variants,dict) or set(variants)!={'correct','mutants'} or not variants['correct'] or not variants['mutants']:raise GraderError('Mutation profile requires correct and mutant variants')
        observations={}
        for kind in ('correct','mutants'):
            for variant in variants[kind]:
                if not isinstance(variant,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',variant):raise GraderError('Invalid variant ID')
                selected=[p for p,n in zip(tests,test_names) if n.startswith('variants/'+variant+'/')]
                if not selected:raise GraderError('Missing declared variant '+variant)
                observations[variant]=_execute(job,config,sources,selected,bundle,toolchain,runtime,True)
                if not observations[variant].get('gradable'):return finish(observations[variant])
        quality=any(r['classification']=='student-test-quality-failure' for r in observations.values())
        correct=all(observations[v].get('score')==1 for v in variants['correct'])
        killed=all(observations[v].get('counts',{}).get('failed',0)>0 for v in variants['mutants'])
        accepted=sum(observations[v].get('score')==1 for v in variants['correct'])
        rejected=sum(observations[v].get('counts',{}).get('failed',0)>0 for v in variants['mutants'])
        message=(('Submission test quality failure: incomplete or disabled tests. ' if quality else '')+
            f"Correct implementations accepted: {accepted}/{len(variants['correct'])}; mutants rejected: {rejected}/{len(variants['mutants'])}. "+
            'Expected outcomes: tests must pass correct implementations and reject every mutant.')
        return finish({'message':message,'gradable':True,'score':float(correct and killed and not quality),'maxPoints':len(observations),'classification':'student-test-quality-failure' if quality else ('success' if correct and killed else 'behavior-failure'),'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','variants':observations,'scoring':config['scoring'],'output':''})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job-dir',type=Path,default=Path('/grade'));parser.add_argument('--verification',action='store_true',help='Private operator verification report; never native student feedback');args=parser.parse_args();status=0
    try:result=grade(args.job_dir)
    except GraderError as error:
        result={'gradable':False,'grading_error':True,'classification':'infrastructure-failure','infrastructure':'failure','message':str(error)};status=2
    if not args.verification:
        import runpy
        boundary=runpy.run_path(str(PLATFORM/'runtime/student_feedback.py'))['student_result']
        try:descriptor=json.loads(_files_any(args.job_dir,'tests/grading-job.json').read_text())
        except (OSError,ValueError):descriptor={}
        result=boundary(result,descriptor)
    path=args.job_dir/'results';path.mkdir(exist_ok=True);path.chmod(0o777);tmp=path/'results.json.tmp';tmp.write_text(json.dumps(result));tmp.replace(path/'results.json');return status

if __name__=='__main__':raise SystemExit(main())
