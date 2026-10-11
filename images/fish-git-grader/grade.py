#!/usr/bin/env python3
"""Изолированное выполнение текстового ответа fish и доверенных проверок."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import tempfile
import time
import types

ROOT=Path(__file__).resolve().parents[2]
RUNTIME='fish-git-v1'
class GraderError(Exception): pass
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def file(root,name):
    if not isinstance(name,str) or not name or '\\' in name or name.startswith('/') or any(x in ('','.','..') for x in name.split('/')): raise GraderError('Unsafe input path')
    p=Path(root)
    for part in name.split('/'):
        p=p/part
        if p.is_symlink(): raise GraderError('Symlink input')
    if not p.is_file() or p.stat().st_size>1048576: raise GraderError('Missing or oversized input')
    return p

def preflight():
    profile=json.loads((ROOT/'runtime-profiles.json').read_text())['profiles'][RUNTIME]
    bundle=ROOT/profile['bundle']
    hashes={p.relative_to(bundle).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.rglob('*') if p.is_file()}
    runner=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if hashes!=profile['files'] or runner!=profile['runnerSha256']: raise GraderError('Runtime dependency closure mismatch')
    supervisor=types.ModuleType('bounded_supervisor')
    exec(compile((bundle/'supervisor.py').read_text(),str(bundle/'supervisor.py'),'exec'),supervisor.__dict__)
    if not shutil.which('fish'): raise GraderError('fish executable unavailable')
    closure={**hashes,'runner/grade.py':runner}
    return supervisor,{'dependencyHashes':closure,'dependencyHash':digest(closure)}

def grade(job_dir):
    entered=time.monotonic()
    job=Path(job_dir).absolute();config=json.loads(file(job/'tests','grading-job.json').read_text())
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((ROOT/'schemas/grading-descriptor.schema.json').read_text())).validate(config)
    if config['runtime']!=RUNTIME or config['mode']!='implementation' or len(config['sourceFiles'])!=1 or not config['sourceFiles'][0].endswith('.fish') or 'checks.py' not in config['testFiles']: raise GraderError('Unsupported fish grading contract')
    supervisor,evidence=preflight()
    official=os.environ.get('PL_CONTAINMENT')=='official'
    prefix=[]
    if official:
        if os.geteuid()!=0 or not Path('/usr/local/bin/landlock_sandbox').is_file(): raise GraderError('Official supervisor required')
        supervisor._protect_input_identity(job)
        job.chmod(0o711)
        for folder in ['student','tests']: (job/folder).chmod(0o700)
        prefix=['runuser','-u','sbuser','--','/usr/local/bin/landlock_sandbox']
    checker=types.ModuleType('trusted_checks');exec(compile(file(job/'tests','checks.py').read_text(),'<trusted-checks>','exec'),checker.__dict__)
    base={'executionEvidence':evidence,'infrastructure':'complete','studentCompilation':'success','trustedCompilation':'success','gradable':True,'containment':'official-landlock-sbuser' if official else 'host-diagnostic','toolchain':'fish','scoring':config['scoring'],'diagnostics':{},'durations':{},'output':''}
    answer_name=config['sourceFiles'][0]
    try:
        source=file(job/'student',answer_name);text=source.read_text(encoding='utf-8')
        if '\0' in text: raise ValueError('NUL')
    except (GraderError,UnicodeError,ValueError):
        return {**base,'studentCompilation':'failure','trustedCompilation':'not-run','gradable':False,'classification':'unsafe-submission','format_errors':'Передайте объявленный текстовый файл fish в UTF-8'}
    cases=checker.cases(job/'tests')
    if not isinstance(cases,list) or not 1<=len(cases)<=16: raise GraderError('Trusted checks require 1..16 explicit cases')
    # Syntax parsing executes no answer commands; runtime execution uses sbuser.
    code,output,reason=supervisor._run(['fish','--no-config','--no-execute',str(source)],job,5)
    if reason: raise GraderError('fish syntax tool failed')
    if code:
        return {**base,'studentCompilation':'failure','trustedCompilation':'not-run','gradable':False,'classification':'student-compilation-failure','format_errors':'Ошибка синтаксиса fish','output':output}
    observations=[];output='';classification=None;started=time.monotonic()
    # Leave time for reporting before the container's hard deadline. A student
    # exceeding the shared execution budget must remain a student timeout.
    deadline=entered+max(0,config['limits']['outer-seconds']-.5)
    for index,case in enumerate(cases):
        with tempfile.TemporaryDirectory(prefix='fish-answer-') as tmp:
            work=Path(tmp);answer=work/answer_name;answer.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,answer)
            if not isinstance(case,dict): raise GraderError('Trusted case must map input paths to UTF-8 text')
            for name,text in case.items():
                if not isinstance(name,str) or name.startswith('/') or '\\' in name or any(x in ('','.','..') for x in name.split('/')) or name==answer_name or not isinstance(text,str) or len(text.encode('utf-8'))>65536: raise GraderError('Unsafe trusted case input')
                path=work/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
            if official:
                account=pwd.getpwnam('sbuser');os.chown(work,account.pw_uid,account.pw_gid)
                for p in work.rglob('*'): os.chown(p,account.pw_uid,account.pw_gid)
            remaining=deadline-time.monotonic()
            if remaining<=0:
                classification='student-timeout'
                break
            code,text,reason=supervisor._run([*prefix,'fish','--no-config',answer_name],work,min(config['limits']['run-seconds'],remaining),config['limits']['max-output-bytes'])
            output=(output+text)[:config['limits']['max-output-bytes']]
            if reason:
                classification='student-timeout' if reason=='timeout' else 'student-output-overflow'
                break
            for name,passed in checker.check(work,case):
                if type(passed) is not bool: raise GraderError('Trusted check must return boolean')
                observations.append((str(index)+': '+name,passed))
    if classification:
        return {**base,'score':0,'classification':classification,'timed_out':classification=='student-timeout','output_limited':classification=='student-output-overflow','message':'Превышен предел выполнения ответа','output':output}
    if len(observations)<config['discovery']['min-executed']: raise GraderError('No trusted checks executed')
    tests=[{'name':name,'description':'','points':int(passed),'max_points':1,'output':'','message':'' if passed else 'Результат не соответствует условию'} for name,passed in observations]
    passed=sum(ok for _,ok in observations);score=passed/len(observations)
    if config['scoring']['mode']=='all-pass': score=float(passed==len(observations))
    elif config['scoring']['mode']!='weighted': raise GraderError('Unsupported fish scoring')
    raw={'score':score,'points':passed,'max_points':len(tests),'gradable':True,'message':'','output':output,'tests':tests}
    counts={'discovered':len(tests),'executed':len(tests),'passed':passed,'failed':len(tests)-passed,'skipped':0,'aborted':0,'containerFailures':0,'outcomes':{name:'successful' if ok else 'failed' for name,ok in observations}}
    return {**base,'score':score,'maxPoints':len(tests),'classification':'success' if score==1 else 'behavior-failure','rawResult':raw,'counts':counts,'tests':tests,'output':output,'durations':{'execution':time.monotonic()-started}}

def main():
    job=Path('/grade')
    try: result=grade(job);status=0
    except Exception as error:
        result={'gradable':False,'grading_error':True,'infrastructure':'failure','classification':'infrastructure-failure','message':str(error)};status=2
    folder=job/'results';folder.mkdir(exist_ok=True);folder.chmod(0o700)
    temporary=folder/'results.json.tmp';temporary.write_text(json.dumps(result,ensure_ascii=False));temporary.chmod(0o600)
    temporary.replace(folder/'results.json')
    # Return the report to the mounted job owner; sbuser was isolated from that
    # UID before any student command. Do not make the report world-writable.
    if os.geteuid()==0:
        owner=job.stat();os.chown(folder/'results.json',owner.st_uid,owner.st_gid);os.chown(folder,owner.st_uid,owner.st_gid)
    return status
if __name__=='__main__': raise SystemExit(main())
