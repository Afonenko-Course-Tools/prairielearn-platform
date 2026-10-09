"""Explicit source inventory -> private /grade jobs -> matching receipts."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import secrets
import jsonschema
ROOT=Path(__file__).resolve().parents[1]
TOOL_VERSION='1.0.0'
class JobError(Exception):pass
class ProjectDefect(JobError):pass
class GradingJob(dict):
    """Serialized contract remains portable; private scratch is not identity."""
    root=None

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def safe(root,name):
    if not isinstance(name,str) or not name or '\\' in name or Path(name).is_absolute() or any(p in ('','.','..') for p in name.split('/')):raise JobError('Unsafe relative path: '+repr(name))
    p=Path(root)
    if p.is_symlink():raise JobError('Symlink root')
    for part in name.split('/'):
        p=p/part
        if p.is_symlink():raise JobError('Symlink path: '+name)
    return p

def validate(name,value):
    try:jsonschema.Draft202012Validator(json.loads((ROOT/'schemas'/f'{name}.schema.json').read_text())).validate(value)
    except (jsonschema.ValidationError,OSError,ValueError) as error:raise JobError(f'Invalid {name}: {error}') from error

def validate_profile(check):validate('project-check',check)
def inventory(manifest):
    if manifest.get('schemaVersion')!=1 or not isinstance(manifest.get('projects'),list):raise JobError('Expected checks manifest version1')
    selected={}
    for p in manifest['projects']:
        if not p.get('check'):continue
        q=p.get('qualifiedId')
        if not isinstance(q,str) or '/' not in q:raise JobError('Missing qualified ID')
        if q in selected and selected[q]!=p:raise JobError('Conflicting duplicate check '+q)
        selected[q]=p
    return [selected[q] for q in sorted(selected)]

def _selection(project,items):
    out=[];names=set()
    for x in items:
        path=safe(project,x['projectRelativePath']);target=x['submissionRelativePath'];safe(project,target)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=x['sha256']:raise JobError('Source snapshot changed: '+x['projectRelativePath'])
        if target in names:raise JobError('Duplicate output source '+target)
        names.add(target);out.append(dict(x))
    return out

def prepare_job(manifest,snapshot,id,scenario,scope='declared',delivery=None):
    projects=[p for p in inventory(manifest) if p['qualifiedId']==id]
    if len(projects)!=1:raise JobError('ID is not in declared check inventory')
    p=projects[0];check=p['check']
    try:validate_profile(check)
    except JobError as error:raise ProjectDefect(str(error)) from error
    snapshot=Path(os.path.abspath(snapshot))
    if snapshot.resolve()!=snapshot:raise JobError('Snapshot root must be an absolute real directory')
    book=safe(Path(snapshot),manifest['bookRoot']);project=safe(book,p['projectRoot'])
    sources=_selection(project,p.get('sources',[]));tests=_selection(project,p.get('trustedTests',[]));public=_selection(project,p.get('verificationTests',[]))
    if p.get('readiness',{}).get('ready') is False or not sources or not tests:raise ProjectDefect('Selected project is incomplete: '+id)
    if p.get('contractCasesHash'):
        x=p['contractCasesHash'];f=safe(project,x['projectRelativePath'])
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=x['sha256']:raise JobError('Contract cases snapshot changed')
    for x in p.get('contractFixtures',[]):
        f=safe(project,x['projectRelativePath'])
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=x['sha256']:raise JobError('Contract fixture snapshot changed: '+x['projectRelativePath'])
    selected=sources
    if scenario.startswith('reference:'):
        name=scenario.split(':',1)[1];refs=[r for r in check.get('references',[]) if r['name']==name]
        if len(refs)!=1:raise JobError('Undeclared reference '+name)
        root=safe(project,refs[0]['root'])
        if not root.is_dir():raise JobError('reference-unavailable:'+name if refs[0].get('optional',False) else 'Missing required reference '+name)
        declared=[r for r in p.get('references',[]) if r['name']==name]
        if len(declared)!=1:raise JobError('Named reference inventory missing '+name)
        selected=_selection(project,declared[0].get('sources',[]))
        if {x['submissionRelativePath'] for x in selected}!={x['submissionRelativePath'] for x in sources}:raise JobError('Reference source mapping differs from student source names')
        for x in sources:
            f=safe(root,x['submissionRelativePath'])
            if not f.is_file():raise JobError('Reference source mapping missing '+x['submissionRelativePath'])
            if not any(y['projectRelativePath']==f.relative_to(project).as_posix() for y in selected):raise JobError('Reference selection does not match declared root')
    elif scenario.startswith('contract:'):
        path=check.get('contract-cases')
        if not path:raise JobError('No declared contract cases')
        cases=json.loads(safe(project,path).read_text());validate('contract-cases',cases)
        if len({c['id'] for c in cases['cases']})!=len(cases['cases']):raise JobError('Duplicate contract case ID')
        case=[c for c in cases['cases'] if c['id']==scenario.split(':',1)[1]]
        if len(case)!=1:raise JobError('Unknown contract case')
        replacements={}
        for x in case[0]['sources']:
            if not x['fixture'].startswith('tests/fixtures/') or x['submission'] not in {s['submissionRelativePath'] for s in sources}:raise JobError('Unauthorized contract fixture/submission')
            f=safe(project,x['fixture'])
            if not f.is_file():raise JobError('Missing contract fixture')
            if x['submission'] in replacements:raise JobError('Duplicate fixture submission')
            replacements[x['submission']]={'projectRelativePath':x['fixture'],'submissionRelativePath':x['submission'],'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
        selected=[replacements.get(x['submissionRelativePath'],x) for x in sources]
    elif scenario!='starter':raise JobError('Unknown scenario')
    java={'release':25,'encoding':'UTF-8','compiler-options':['-proc:none','-Xmaxerrs','5']};java.update(check.get('java',{}))
    limits={'outer-seconds':30,'compile-seconds':15,'run-seconds':10,'networking':False,'max-output-bytes':65536};limits.update(check.get('limits',{}))
    grading={'schemaVersion':1,'sourceFiles':[x['submissionRelativePath'] for x in selected],'testFiles':[x['submissionRelativePath'] for x in tests],'mode':check.get('mode',check.get('sourceProfile',{}).get('mode','implementation')),'runtime':check['runtime'],'java':java,'limits':limits,'scoring':check.get('scoring',{'mode':'weighted'}),'discovery':check.get('discovery',{'min-executed':1,'allow-skipped':False})}
    if 'variants' in check:grading['variants']=check['variants']
    runtime=json.loads((ROOT/'runtime-profiles.json').read_text())['profiles'][check['runtime']]
    expectations=case[0]['expected'] if scenario.startswith('contract:') else check.get('verification-expectations',{}).get('reference' if scenario.startswith('reference:') else 'starter',{})
    job=GradingJob(schemaVersion=1,scope=scope,qualifiedId=id,scenario=scenario,sourceSnapshotHash=manifest['sourceSnapshotHash'],inventoryHash=manifest['inventoryHash'],runtime=check['runtime'],imageDigest=runtime['image'] or os.environ.get('PL_LOCAL_IMAGE_ID'),sources=selected,trustedTests=tests,verificationTests=public,grading=grading,expectations=expectations,sourceHashes={x['projectRelativePath']:x['sha256'] for x in selected},testsHashes={x['projectRelativePath']:x['sha256'] for x in [*tests,*public]})
    if scope=='delivery':
        if not delivery or id not in delivery.get('questions',[]):raise JobError('ID absent from delivery')
        job['deliveryHash']=delivery['deliveryHash']
        canonical={k:v for k,v in delivery.items() if k not in ('deliveryHash','_root')}
        if digest(canonical)!=delivery['deliveryHash']:raise JobError('Delivery manifest content hash mismatch')
        if delivery.get('sourceSnapshotHash')!=manifest['sourceSnapshotHash'] or delivery.get('inventoryHash')!=manifest['inventoryHash']:raise JobError('Delivery does not match source/check inventory')
        native=Path(delivery.get('_root',''))
        if not native.is_dir() or native.resolve()!=native.absolute():raise JobError('Actual native delivery root is required')
        for filename,expected_hash in delivery.get('files',{}).items():
            file=safe(native,filename)
            if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected_hash:raise JobError('Native delivery file hash mismatch: '+filename)
        question=safe(native,'questions/'+id)
        info=json.loads(safe(question,'info.json').read_text())
        if info.get('externalGradingOptions',{}).get('image')!=job['imageDigest']:raise JobError('Exported runtime image differs from verification image; export a fresh delivery')
        actual=json.loads(safe(question,'tests/grading-job.json').read_text())
        if actual!=grading:raise JobError('Exported grading descriptor/profile differs from selected check')
        for x in tests:
            f=safe(question,'tests/'+x['submissionRelativePath'])
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=x['sha256']:raise JobError('Exported trusted suite differs from snapshot')
        for x in sources:
            f=safe(question,'serverFilesQuestion/starter/'+x['submissionRelativePath'])
            if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=x['sha256']:raise JobError('Exported starter differs from snapshot')
    validate('grading-job',job)
    job.root=Path(tempfile.mkdtemp(prefix='grading-job-'))
    for folder,selection in [('student',selected),('tests',tests)]:
        for x in selection:
            target=safe(job.root,folder+'/'+x['submissionRelativePath']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(safe(project,x['projectRelativePath']).read_bytes())
    (job.root/'tests/grading-job.json').write_text(json.dumps(grading,sort_keys=True))
    if public:
        publicroot=job.root/'public-verification';(publicroot/'student').mkdir(parents=True);(publicroot/'tests').mkdir()
        shutil.copytree(job.root/'student',publicroot/'student',dirs_exist_ok=True)
        for x in public:
            target=safe(publicroot,'tests/'+x['submissionRelativePath']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(safe(project,x['projectRelativePath']).read_bytes())
        cfg=dict(grading,testFiles=[x['submissionRelativePath'] for x in public],scoring={'mode':'weighted'})
        (publicroot/'tests/grading-job.json').write_text(json.dumps(cfg,sort_keys=True))
    return job

def run_job(job,backend='host'):
    validate('grading-job',job)
    if not getattr(job,'root',None):raise JobError('Prepared private job root required')
    common={k:job[k] for k in ('scope','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','runtime','imageDigest','sourceHashes','testsHashes')}
    if 'deliveryHash' in job:common['deliveryHash']=job['deliveryHash']
    try:
        if backend=='host':
            spec=importlib.util.spec_from_file_location('platform_grader',ROOT/'images/java25-grader/grade.py');grader=importlib.util.module_from_spec(spec);spec.loader.exec_module(grader)
            try:result=grader.grade(job.root)
            except grader.GraderError as error:raise JobError(str(error)) from error
        elif backend=='container':
            if not job['imageDigest']:raise JobError('Runtime production image has not been built/published')
            job.containerName='plcheck-'+secrets.token_hex(12)
            cmd=['docker','run','--rm','--name',job.containerName,'--network','none','--cpus','0.9','--memory','512m','--pids-limit','128','--mount',f'type=bind,src={job.root},dst=/grade',job['imageDigest']]
            try:p=subprocess.run(cmd,capture_output=True,text=True,timeout=job['grading']['limits']['outer-seconds'])
            except subprocess.TimeoutExpired as error:
                cleanup=subprocess.run(['docker','rm','--force',job.containerName],capture_output=True,text=True,timeout=10)
                if cleanup.returncode and 'No such container' not in cleanup.stderr:raise JobError('Outer Docker timeout; container cleanup failed: '+cleanup.stderr) from error
                raise JobError('Outer Docker timeout; container removed') from error
            if p.returncode not in (0,2):raise JobError('Docker infrastructure failure: '+p.stderr)
            result=json.loads((job.root/'results/results.json').read_text())
        else:raise JobError('Unknown backend')
    except (JobError,OSError,ValueError,subprocess.TimeoutExpired) as error:result={'infrastructure':'failure','classification':'infrastructure-failure','gradable':False,'grading_error':True,'message':str(error)}
    if (job.root/'public-verification').is_dir() and result.get('infrastructure')=='complete':
        publicjob=GradingJob(job);publicjob.root=job.root/'public-verification'
        publicresult=run_job(publicjob,backend)
        result['publicResult']={k:v for k,v in publicresult.items() if k not in {'schemaVersion','scope','qualifiedId','scenario','sourceSnapshotHash','inventoryHash','deliveryHash','runtime','imageDigest','sourceHashes','testsHashes','backend'}}
        if publicresult.get('infrastructure')!='complete':result.update(infrastructure='failure',classification='infrastructure-failure')
    value={'schemaVersion':1,'backend':backend,**common,**result}
    validate('check-result',value)
    return value

def _matches(result,expected):
    keys={'student-compilation':'studentCompilation','classification':'classification'}
    for key,field in keys.items():
        if key in expected and result.get(field)!=expected[key]:return False,key
    if 'job' in expected and ('complete' if result.get('infrastructure')=='complete' else 'failure')!=expected['job']:return False,'job'
    c=result.get('counts',{})
    if expected.get('required-tests')=='all-pass' and result.get('publicResult'):
        public=result['publicResult'].get('counts',{})
        if public.get('executed',0)<1 or public.get('failed',0) or public.get('skipped',0) or public.get('aborted',0):return False,'public-required-tests'
    if expected.get('required-tests')=='all-pass' and result.get('variants') and result.get('classification')!='success':return False,'mutation-contracts'
    if expected.get('required-tests')=='all-pass' and not result.get('variants') and (c.get('executed',0)<1 or c.get('failed',0) or c.get('skipped',0) or c.get('aborted',0)):return False,'required-tests'
    for name,actual in [('failed-tests',c.get('failed',0)),('executed-tests',c.get('executed',0)),('score',result.get('score'))]:
        if name in expected:
            if actual is None:return False,name
            for op,want in expected[name].items():
                if (op=='at-least' and actual<want) or (op=='exactly' and actual!=want) or (op=='less-than' and actual>=want):return False,name
    if 'test-ids' in expected and not set(expected['test-ids']).issubset(c.get('outcomes',{})):return False,'test-ids'
    return True,''

def verify_results(results,expectations):
    if not results:raise JobError('No results; empty receipt forbidden')
    first=results[0];status=0;checks=[]
    for r in results:
        for k in ('scope','sourceSnapshotHash','inventoryHash','deliveryHash','backend'):
            if r.get(k)!=first.get(k):raise JobError('Mixed snapshot/scope receipts forbidden')
        e={'student-compilation':'success','job':'complete','required-tests':'all-pass'} if r['scenario'].startswith('reference:') else {}
        e.update(expectations.get(r['qualifiedId']+':'+r['scenario'],expectations.get(r['scenario'],{})));matched,reason=_matches(r,e)
        infrastructure=r.get('infrastructure')!='complete'
        if infrastructure:status=2;matched=False;reason='infrastructure'
        elif not matched or r.get('studentCompilation')!='success':status=max(status,1)
        checks.append({'qualifiedId':r['qualifiedId'],'scenario':r['scenario'],'matched':matched,'reason':reason})
    registry=json.loads((ROOT/'runtime-profiles.json').read_text())
    receipt={'schemaVersion':1,'toolVersion':TOOL_VERSION,'backend':first.get('backend','host'),'scope':first['scope'],'sourceSnapshotHash':first['sourceSnapshotHash'],'inventoryHash':first['inventoryHash'],'status':['success','defect','infrastructure-failure'][status],'exitCode':status,'checkedIds':sorted(set(r['qualifiedId'] for r in results)),'runtimes':{r['runtime']:r.get('imageDigest') for r in results},'dependencyHashes':{r['runtime']+'/'+name:h for r in results for name,h in registry['profiles'][r['runtime']]['files'].items()},'expectations':checks}
    if 'deliveryHash' in first:receipt['deliveryHash']=first['deliveryHash']
    receipt['dependencyHashes'].update({'runner/grade.py':registry['profiles'][first['runtime']]['runnerSha256'],**{'schema/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'schemas').glob('*.json'))}})
    receipt['identityHash']=digest(receipt);validate('verification-receipt',receipt);return receipt
