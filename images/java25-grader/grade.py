#!/usr/bin/env python3
"""One explicit JDK25/official JUnit runner for host and /grade jobs."""
import argparse
import hashlib
import shutil
import json
import os
from pathlib import Path, PurePosixPath
import re
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


def _run(command, cwd, timeout, output_limit=OUTPUT_LIMIT):
    try:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
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

def _class_names(files):
    names=[]
    for f in files:
        text=Path(f).read_text(encoding='utf-8')
        package=re.search(r'^\s*package\s+([\w.]+)\s*;',text,re.M)
        prefix=package[1]+'.' if package else ''
        # Include package-private top-level classes, enums and records too.
        classes=re.findall(r'\b(?:class|interface|enum|record)\s+(\w+)',text)
        names.extend(prefix+x for x in classes)
    return names

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
    allowed={'schemaVersion','sourceFiles','testFiles','mode','runtime','java','limits','scoring','discovery','variants'}
    if not isinstance(config,dict) or set(config)-allowed or config.get('schemaVersion')!=1:
        raise GraderError('Expected closed schemaVersion1 JUnit grading descriptor')
    if config.get('mode') not in ('implementation','student-tests'):raise GraderError('Invalid submission mode')
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
        files=[str(self.bundle/'PlatformJUnitAdapter.java'),*map(str,(self.bundle/'upstream').rglob('*.java'))]
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


def _execute(job,config,sources,tests,bundle,toolchain,runtime,student_tests=False):
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
        reserved=('org.junit.','org.prairielearn.','org.json.','java.','javax.','PlatformJUnitAdapter','JUnitAutograder')
        if any(n.startswith(reserved) for n in _class_names(sources)) or set(_class_names(sources))&set(_class_names(tests)):
            return _invalid('Submitted classes collide with trusted namespaces',classification='unsafe-submission')
        if student_tests:
            code,reason=compile_phase('trustedCompilation',tests,trusted,libs)
            if code or reason:raise GraderError('Trusted fixture compilation failed: '+diagnostics['trustedCompilation'])
            code,reason=compile_phase('studentCompilation',sources,student,os.pathsep.join([libs,str(trusted)]))
        else:
            code,reason=compile_phase('studentCompilation',sources,student,libs)
        if reason:raise GraderError('Student compilation infrastructure limit: '+reason)
        if code:return _invalid('Your submission could not be compiled',diagnostics['studentCompilation'])
        if not student_tests:
            code,reason=compile_phase('trustedCompilation',tests,trusted,os.pathsep.join([libs,str(student)]))
            if code or reason:raise GraderError('Trusted suite compilation failed: '+diagnostics['trustedCompilation'])
        student_fqcn={x.relative_to(student).as_posix() for x in student.rglob('*.class')}
        trusted_fqcn={x.relative_to(trusted).as_posix() for x in trusted.rglob('*.class')}
        if student_fqcn&trusted_fqcn:return _invalid('Submitted classes collide with trusted classes',classification='unsafe-submission')
        runtime.ensure_adapter(job,limits,durations,diagnostics)
        reports=stage/'results';reports.mkdir()
        params=stage/'params';params.mkdir()
        rawfile=reports/(secrets.token_hex(32)+'.json');countfile=reports/(secrets.token_hex(32)+'.json');signature=secrets.token_hex(32)
        parameter_file=params/'params.json'
        parameter_file.write_text(json.dumps({'results_file':str(rawfile),'counts_file':str(countfile),'signature':signature,'test_classes':_source_classes(sources if student_tests else tests)}))
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
        classpath=os.pathsep.join([str(adapter),libs,str(trusted),str(student)])
        command=[*prefix,'java','-Xmx128m','-XX:TieredStopAtLevel=1','-XX:ActiveProcessorCount=2','-XX:-UsePerfData','-XX:+DisableAttachMechanism','--illegal-native-access=deny','-cp',classpath,'PlatformJUnitAdapter',str(parameter_file)]
        start=time.monotonic();code,text,reason=_run(command,job,limits.get('run-seconds',10),int(limits['max-output-bytes']));durations['execution']=time.monotonic()-start
        base={'gradable':True,'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','durations':durations,'diagnostics':diagnostics,'toolchain':toolchain,'containment':containment,'scoring':config['scoring'],'output':text}
        if reason:
            base.update(score=0,classification='student-timeout' if reason=='timeout' else 'student-output-overflow',timed_out=reason=='timeout',output_limited=reason=='output_limit')
            return base
        if code!=0 or not rawfile.is_file() or not countfile.is_file():raise GraderError('JUnit execution did not produce complete reports')
        try:
            raw=json.loads(rawfile.read_text());counts=json.loads(countfile.read_text())
            if raw.pop('signature')!=signature or counts.pop('signature')!=signature:raise ValueError('signature')
        except (KeyError,ValueError,OSError) as error:raise GraderError('Invalid JUnit report') from error
        base.update(rawResult=raw,counts=counts,maxPoints=raw['max_points'])
        incomplete=counts['executed']<config['discovery']['min-executed'] or counts['discovered']==0 or counts['aborted']>0 or counts['containerFailures']>0 or (counts['skipped']>0 and not config['discovery']['allow-skipped'])
        if incomplete or not raw.get('gradable'):
            if not student_tests:raise GraderError('Trusted JUnit discovery/execution is incomplete')
            base.update(score=0,classification='student-test-quality-failure');return base
        base.update(score=_score(raw,counts,config['scoring']),classification='behavior-failure' if counts['failed'] else 'success')
        return base

def grade(job_dir):
    job=Path(job_dir).absolute()
    try:config=json.loads(_files_any(job,'tests/grading-job.json').read_text())
    except (OSError,ValueError) as error:raise GraderError('Missing or invalid grading configuration') from error
    validate_config(config);profile,bundle,toolchain=preflight(config['runtime'])
    closure={**profile['files'],'runner/grade.py':profile['runnerSha256']}
    evidence={'dependencyHashes':closure,'dependencyHash':hashlib.sha256(json.dumps(closure,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
    def finish(value):
        value['executionEvidence']=evidence
        return value
    if profile['mode']!=config['mode']:raise GraderError('Runtime mode mismatch')
    source_names=_names(config,'sourceFiles');test_names=_names(config,'testFiles')
    try:tests=_files(job/'tests',test_names)
    except ValueError as error:raise GraderError('Missing or unsafe trusted sources') from error
    try:sources=_files(job/'student',source_names)
    except ValueError:return finish(_invalid('Upload all declared Java files'))
    with tempfile.TemporaryDirectory(prefix='java25-job-runtime-') as runtime_dir:
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
        return finish({'gradable':True,'score':float(correct and killed and not quality),'maxPoints':len(observations),'classification':'student-test-quality-failure' if quality else ('success' if correct and killed else 'behavior-failure'),'studentCompilation':'success','trustedCompilation':'success','infrastructure':'complete','variants':observations,'scoring':config['scoring'],'output':''})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job-dir',type=Path,default=Path('/grade'));args=parser.parse_args();status=0
    try:result=grade(args.job_dir)
    except GraderError as error:
        print('Grader failure: '+str(error),file=sys.stderr);result={'gradable':False,'grading_error':True,'classification':'infrastructure-failure','infrastructure':'failure','message':str(error)};status=2
    path=args.job_dir/'results';path.mkdir(exist_ok=True);path.chmod(0o777);tmp=path/'results.json.tmp';tmp.write_text(json.dumps(result));tmp.replace(path/'results.json');return status

if __name__=='__main__':raise SystemExit(main())
