"""Проверка actual native пакета; не исполняет и не оценивает ручной ответ."""
import hashlib,json,re,stat,uuid
from html.parser import HTMLParser
from pathlib import Path
import jsonschema
from grading_job import ROOT,JobError,digest,safe

HASH=re.compile(r'^[a-f0-9]{64}$')
def relative_name(value):
 return isinstance(value,str) and bool(value) and not value.startswith('/') and not re.match(r'^[A-Za-z]:',value) and not re.search(r'[\x00-\x1f\x7f]',value) and '\\' not in value and not any(part in ('','.','..') for part in value.split('/'))
def file_bytes(root,name):
 try:
  path=safe(root,name)
  if not stat.S_ISREG(path.lstat().st_mode):raise JobError('Native package requires regular files')
  return path.read_bytes()
 except OSError as error:raise JobError('Missing native package file: '+name) from error

def native_schema(name,value):
 folder=ROOT/'schemas/native-upstream';manifest=json.loads((folder/'manifest.json').read_text())
 for file,sha in manifest['files'].items():
  if hashlib.sha256(file_bytes(folder,file)).hexdigest()!=sha:raise JobError('Pinned native schema dependency changed')
 try:jsonschema.Draft7Validator(json.loads(file_bytes(folder,name))).validate(value)
 except jsonschema.ValidationError as error:raise JobError('Invalid native '+name+': '+error.message) from error

class Controls(HTMLParser):
 def __init__(self,html):
  super().__init__(convert_charrefs=True);self.elements=[];self.feed(html);self.close()
 def handle_starttag(self,tag,attrs):
  if tag.startswith('pl-'):
   if len({key for key,_ in attrs})!=len(attrs):raise JobError('Ambiguous native control attributes')
   self.elements.append((tag,dict(attrs)))


def upload_values(attrs,key,paths=True):
 if key not in attrs:return []
 value=attrs[key]
 if not isinstance(value,str):raise JobError('Empty native upload attribute')
 values=[part.strip() for part in value.split(',')]
 if not values or any(not part or (paths and not relative_name(part)) for part in values) or len(set(values))!=len(values):raise JobError('Invalid native upload names/patterns')
 return values


def classification(delivery):
 if not isinstance(delivery,dict) or delivery.get('schemaVersion')!=3:raise JobError('Unsupported native delivery; v3 required')
 required={'schemaVersion','courseId','bookRoot','sourceSnapshotHash','inventoryHash','verificationInventoryHash','questions','gradingPayloads','works','instances','files','deliveryHash'}
 if not required<=delivery.keys() or set(delivery)-required-{'candidate'} or not isinstance(delivery.get('courseId'),str) or not re.fullmatch(r'[a-z][a-z0-9-]*',delivery['courseId']):raise JobError('Closed canonical delivery v3 required')
 if any(not isinstance(delivery.get(k),str) or not HASH.fullmatch(delivery[k]) for k in ('sourceSnapshotHash','inventoryHash','verificationInventoryHash','deliveryHash')):raise JobError('Invalid delivery hash binding')
 if not isinstance(delivery['works'],list) or not delivery['works'] or not isinstance(delivery['instances'],dict) or not delivery['instances']:raise JobError('Native work/instance catalog required')
 if 'candidate' in delivery and type(delivery['candidate']) is not bool:raise JobError('Invalid candidate marker')
 questions=delivery.get('questions');bindings=delivery.get('gradingPayloads')
 if not isinstance(questions,list) or not questions or any(not isinstance(q,str) or not re.fullmatch(re.escape(delivery.get('courseId',''))+r'/exr-[a-z0-9][a-z0-9-]*',q) for q in questions) or len(set(questions))!=len(questions):raise JobError('Exact unique nonempty question catalog required')
 if not isinstance(bindings,dict) or set(bindings)!=set(questions):raise JobError('Exact grading binding catalog required')
 methods={};uuids=set()
 for q in questions:
  binding=bindings[q]
  if not isinstance(binding,dict) or not {'uuid','grading','submission','sourceRoot'}<=binding.keys():raise JobError('Canonical grading/submission binding required')
  grading=binding['grading'];submission=binding['submission']
  if not isinstance(grading,dict) or set(grading)!={'method'} or grading['method'] not in ('external','mixed','manual'):raise JobError('Explicit canonical grading method required')
  method=grading['method'];allowed={'uuid','grading','submission','sourceRoot'}|({'projectCheck','runtime','sources'} if method!='manual' else set())
  if set(binding)!=allowed:raise JobError('Closed method-specific question binding required')
  if not isinstance(submission,dict) or set(submission)-{'mode','aceMode'} or submission.get('mode') not in ('upload','editor') or submission.get('mode')=='upload' and 'aceMode' in submission:raise JobError('Closed canonical submission required')
  if 'aceMode' in submission and (not isinstance(submission['aceMode'],str) or not submission['aceMode']):raise JobError('Invalid editor mode')
  if method=='manual' and submission['mode']!='upload':raise JobError('Manual requires actual native upload')
  try:valid_uuid=isinstance(binding['uuid'],str) and str(uuid.UUID(binding['uuid']))==binding['uuid'].lower()
  except ValueError:valid_uuid=False
  if not valid_uuid or binding['uuid'] in uuids:raise JobError('Unique canonical question UUIDs required')
  if not relative_name(binding['sourceRoot']):raise JobError('Invalid owner-relative project source root')
  if method!='manual':
   if any(not isinstance(binding[k],str) or not binding[k] for k in ('projectCheck','runtime')) or not isinstance(binding['sources'],list) or not binding['sources']:raise JobError('Automatic source/check binding required')
   targets=set()
   for source in binding['sources']:
    if not isinstance(source,dict) or set(source)!={'projectRelativePath','submissionRelativePath','sha256'} or any(not relative_name(source[k]) for k in ('projectRelativePath','submissionRelativePath')) or not isinstance(source['sha256'],str) or not HASH.fullmatch(source['sha256']) or source['submissionRelativePath'] in targets:raise JobError('Invalid or duplicate automatic source binding')
    targets.add(source['submissionRelativePath'])
  uuids.add(binding['uuid']);methods[q]=method
 return methods


def package_integrity(delivery,native,checks=None):
 native=Path(native);methods=classification(delivery)
 if all(method=='manual' for method in methods.values()) and delivery['verificationInventoryHash']!=digest([]):raise JobError('Wholly manual delivery cannot declare automatic scenarios')
 if digest({k:v for k,v in delivery.items() if k!='deliveryHash'})!=delivery.get('deliveryHash'):raise JobError('Canonical delivery identity mismatch')
 if checks is not None and any(delivery.get(k)!=checks.get(k) for k in ('sourceSnapshotHash','inventoryHash')):raise JobError('Package/check source identity differs')
 files=delivery.get('files')
 if not isinstance(files,dict) or not files or not all(isinstance(sha,str) and HASH.fullmatch(sha) for sha in files.values()):raise JobError('Nonempty canonical native inventory required')
 for name,sha in files.items():
  if hashlib.sha256(file_bytes(native,name)).hexdigest()!=sha:raise JobError('Native package bytes differ: '+name)
 def read(name):
  if name not in files:raise JobError('Native metadata absent from canonical inventory')
  try:return json.loads(file_bytes(native,name))
  except ValueError as error:raise JobError('Invalid native JSON') from error
 native_schema('infoCourse.json',read('infoCourse.json'))
 for name in files:
  if re.fullmatch(r'courseInstances/[^/]+/infoCourseInstance.json',name):native_schema('infoCourseInstance.json',read(name))
 covered=set();works={work.get('id'):work for work in delivery['works'] if isinstance(work,dict)}
 if len(works)!=len(delivery['works']) or any(not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9-]*',key) for key in works):raise JobError('Unique canonical work identities required')
 for instance,catalog in delivery['instances'].items():
  if not isinstance(instance,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*',instance) or not isinstance(catalog,dict) or set(catalog)!={'works','selfEnrollment'} or type(catalog['selfEnrollment']) is not bool or not isinstance(catalog['works'],list) or not catalog['works'] or len(set(catalog['works']))!=len(catalog['works']) or any(work not in works for work in catalog['works']):raise JobError('Exact canonical instance work catalog required')
  instance_path='courseInstances/'+instance+'/infoCourseInstance.json'
  if instance_path not in files:raise JobError('Native instance metadata missing')
  for work_id in catalog['works']:
   work=works[work_id];name='courseInstances/'+instance+'/assessments/'+work_id+'/infoAssessment.json'
   assessment=read(name);native_schema('infoAssessment.json',assessment)
   if set(work)-{'id','slots','policy','completion','relatedExercise'} or not {'id','slots','policy','completion'}<=set(work) or not isinstance(work['policy'],dict):raise JobError('Closed canonical work required')
   slots=work.get('slots')
   if not isinstance(slots,list) or not slots:raise JobError('Canonical nonempty work slots required')
   groups=[(zone,group) for zone in assessment['zones'] for group in zone['questions']];used=set();slot_ids=set();candidates=set()
   for slot in slots:
    if not isinstance(slot,dict) or set(slot)!={'id','selection','candidates','assignment'} or not isinstance(slot['id'],str) or slot['id'] in slot_ids or not slot['id'].startswith(delivery['courseId']+'/'+work_id+'/'):raise JobError('Canonical closed slot identity required')
    assignment=slot['assignment']
    if not isinstance(assignment,dict) or not {'requirement','workMode'}<=set(assignment) or set(assignment)-{'requirement','workMode','stage'} or assignment['requirement'] not in ('required','optional') or assignment['workMode'] not in ('individual','pair','group') or 'stage' in assignment and assignment['stage'] not in ('demonstration','classroom','homework'):raise JobError('Closed canonical slot assignment required')
    slot_ids.add(slot['id']);pool=slot['candidates'];selection=slot['selection']
    if selection not in ('fixed','random','choice') or not isinstance(pool,list) or not pool or len(set(pool))!=len(pool) or any(q not in methods or q in candidates for q in pool):raise JobError('Invalid canonical candidate pool')
    if selection=='fixed' and (len(pool)!=1 or slot['id'].split('/')[-1]!=pool[0].split('/')[-1]) or selection!='fixed' and (len(pool)<2 or not re.fullmatch(r'alt-[a-z0-9][a-z0-9-]*',slot['id'].split('/')[-1])):raise JobError('Invalid canonical slot selection')
    if selection=='choice':
     if slot['assignment'].get('requirement')!='required':raise JobError('Choice must be required')
     matches=[(i,zone,group) for i,(zone,group) in enumerate(groups) if 'alternatives' not in group and group.get('id') in pool]
     if len(matches)!=len(pool) or len({group['id'] for _,_,group in matches})!=len(pool) or len({id(zone) for _,zone,_ in matches})!=1:raise JobError('Actual choice candidates must share one complete zone')
     zone=matches[0][1]
     if zone.get('bestQuestions')!=1 or 'numberChoose' in zone or len(zone['questions'])!=len(pool) or any('numberChoose' in group or i in used for i,_,group in matches):raise JobError('Choice zone must expose all candidates with bestQuestions one')
     used.update(i for i,_,_ in matches)
    else:
     matches=[(i,zone,group) for i,(zone,group) in enumerate(groups) if sorted(q['id'] for q in group.get('alternatives',[group]))==sorted(pool)]
     if len(matches)!=1:raise JobError('Actual native group differs from canonical slot')
     i,zone,group=matches[0]
     if i in used or 'bestQuestions' in zone or 'numberChoose' in zone or selection=='random' and group.get('numberChoose')!=1 or selection=='fixed' and ('alternatives' in group or group.get('numberChoose',1)!=1):raise JobError('Actual fixed/random group selection differs')
     used.add(i)
    candidates.update(pool)
   if used!=set(range(len(groups))):raise JobError('Unbound native assessment group')
   completion=work['completion'];ordered=[slot['id'] for slot in slots];required=[slot['id'] for slot in slots if slot['assignment']['requirement']=='required']
   if not isinstance(completion,dict) or set(completion)!={'schemaVersion','mode','source','slotIds','requiredSlotIds','atLeast','fullyCompletedScore'} or type(completion['schemaVersion']) is not int or completion['schemaVersion']!=2 or completion['mode']!='required-slot-completion' or completion['source']!='per-slot-results-v2' or type(completion['fullyCompletedScore']) is not int or completion['fullyCompletedScore']!=1 or completion['slotIds']!=ordered or completion['requiredSlotIds']!=required or type(completion['atLeast']) is not int or not 1<=completion['atLeast']<=len(required):raise JobError('Canonical completion differs from native slot catalog')
   for zone,group in groups:
    for question in group.get('alternatives',[group]):
     q=question['id'];covered.add(q);method=methods[q];auto=question.get('autoPoints',group.get('autoPoints',question.get('points',group.get('points'))));manual=question.get('manualPoints',group.get('manualPoints'))
     if method=='manual' and (auto not in (None,0) or type(manual) not in (int,float) or manual<=0):raise JobError('Manual component mismatch')
     if method=='mixed' and (type(auto) not in (int,float) or auto<=0 or type(manual) not in (int,float) or manual<=0):raise JobError('Mixed requires both native components')
     if method=='external' and manual is not None:raise JobError('External cannot hide a manual component')
 if covered!=set(methods):raise JobError('Exact assessment question coverage required')
 facts={}
 for project in (checks or {}).get('projects',[]):
  q=project.get('qualifiedId')
  if q in facts:raise JobError('Duplicate private project binding')
  facts[q]=project
 result=[]
 for q,method in sorted(methods.items()):
  binding=delivery['gradingPayloads'][q];prefix='questions/'+q+'/';question_files={name[len(prefix):]:sha for name,sha in files.items() if name.startswith(prefix)}
  if not question_files:raise JobError('Question has no canonical files')
  folder=safe(native,'questions/'+q);actual=set()
  for path in folder.rglob('*'):
   if path.is_symlink() or not (path.is_dir() or path.is_file()):raise JobError('Unsafe native question tree')
   if path.is_file():actual.add(path.relative_to(folder).as_posix())
  if actual!=set(question_files):raise JobError('Question file inventory differs from canonical delivery')
  info=read(prefix+'info.json');native_schema('infoQuestion.json',info)
  if info['uuid']!=binding['uuid'] or info.get('gradingMethod')!=('Manual' if method=='manual' else 'External'):raise JobError('Native method/UUID differs from canonical binding')
  controls=Controls(file_bytes(native,prefix+'question.html').decode('utf-8')).elements
  uploads=[attrs for tag,attrs in controls if tag=='pl-file-upload'];editors=[attrs for tag,attrs in controls if tag=='pl-file-editor']
  descriptor=None
  if method!='manual':
   descriptor=read(prefix+'tests/grading-job.json')
   from grading_job import validate
   validate('grading-descriptor',descriptor)
  names=[];optional=[];patterns=[]
  for attrs in uploads:
   required=upload_values(attrs,'file-names');extra=upload_values(attrs,'optional-file-names')
   globs=upload_values(attrs,'file-patterns',False)+upload_values(attrs,'optional-file-patterns',False)
   if not required and not extra and not globs:raise JobError('Native upload input missing or empty')
   names.extend(required);optional.extend(extra);patterns.extend(globs)
  if len(set(names+optional))!=len(names+optional):raise JobError('Duplicate native upload name')
  if method!='manual':
   extra_policy=descriptor.get('additionalJavaSources');optional_primary=extra_policy is not None and extra_policy.get('primaryRequired',True) is False
   expected_optional=([*[source['submissionRelativePath'] for source in binding['sources'] if '/' not in source['submissionRelativePath']],extra_policy['archive']] if optional_primary else [extra_policy['archive']]) if extra_policy else []
   if optional_primary and binding['submission']['mode']!='upload':raise JobError('Optional primary requires upload')
   if patterns or sorted(optional)!=sorted(expected_optional):raise JobError('Native upload optional files differ from declared policy')
  if binding['submission']['mode']=='upload':
   if editors or not uploads:raise JobError('Native upload input missing or empty')
   if method!='manual' and set(names)!=(set() if optional_primary else {source['submissionRelativePath'] for source in binding['sources']}):raise JobError('Native upload inputs differ from bound source files')
  else:
   if names:raise JobError('Editor cannot add required upload names')
   expected=[source['submissionRelativePath'] for source in binding['sources']]
   if not editors or len({a.get('file-name') for a in editors})!=len(editors) or {a.get('file-name') for a in editors}!=set(expected):raise JobError('Native editor inputs differ from bound source files')
  if not any(name.startswith('clientFilesQuestion/') for name in question_files):raise JobError('Public starter/resource files missing')
  if method=='manual':
   if q in facts or 'externalGradingOptions' in info or any(name.startswith('tests/') or name in ('server.py','server.js','server.ts') for name in question_files) or any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Manual no-grader contract violated')
  else:
   if checks is not None:
    fact=facts.get(q)
    if not fact or not fact.get('check') or fact.get('readiness',{}).get('ready') is False:raise JobError('Automatic question needs ready private check')
    if binding['sourceRoot']!=fact.get('projectRoot') or binding['runtime']!=fact['check'].get('runtime') or binding['projectCheck']!=fact['check'].get('profile') or binding['sources']!=fact.get('sources'):raise JobError('Automatic source/check binding differs')
   if descriptor['runtime']!=binding['runtime'] or not info.get('externalGradingOptions',{}).get('image') or not any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Automatic runtime/native control missing')
  result.append({'qualifiedId':q,'method':method,'uuid':binding['uuid'],'submissionMode':binding['submission']['mode'],'questionFilesHash':digest(question_files)})
 return {'status':'success','coverage':'complete','filesHash':digest(files),'questionBindings':result}


def delivery_receipt(delivery,native,checks,automatic=None,registry=None):
 from grading_job import TOOL_VERSION,validate_release_receipt
 package=package_integrity(delivery,native,checks);methods=classification(delivery)
 auto={q for q,method in methods.items() if method!='manual'}
 if auto and automatic is None:raise JobError('Automatic proof missing')
 if not auto and automatic is not None:raise JobError('Wholly manual does not accept grading results')
 proof={'state':'verified','receipt':automatic} if auto else {'state':'not-applicable','reason':'all-questions-manual'}
 result={'schemaVersion':3,'kind':'delivery-verification','scope':'delivery','toolVersion':TOOL_VERSION,**{k:delivery[k] for k in ('deliveryHash','sourceSnapshotHash','inventoryHash')},'packageIntegrity':package,'automatic':proof}
 result['identityHash']=digest(result);validate_release_receipt(result,delivery,native,registry);return result
