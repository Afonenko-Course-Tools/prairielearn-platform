"""Проверка actual native пакета; не исполняет и не оценивает ручной ответ."""
import json,re,stat,uuid
from html.parser import HTMLParser
from pathlib import Path
import jsonschema
from grading_job import ROOT,JobError,safe

def relative_name(value):
 return isinstance(value,str) and bool(value) and not value.startswith('/') and not re.match(r'^[A-Za-z]:',value) and not re.search(r'[\x00-\x1f\x7f]',value) and '\\' not in value and not any(part in ('','.','..') for part in value.split('/'))
def file_bytes(root,name):
 try:
  path=safe(root,name)
  if not stat.S_ISREG(path.lstat().st_mode):raise JobError('Native package requires regular files')
  return path.read_bytes()
 except OSError as error:raise JobError('Missing native package file: '+name) from error

def native_schema(name,value):
 folder=ROOT/'schemas/native-upstream'
 try:jsonschema.Draft7Validator(json.loads(file_bytes(folder,name))).validate(value)
 except jsonschema.ValidationError as error:raise JobError('Invalid native '+name+': '+error.message) from error

class Controls(HTMLParser):
 def __init__(self,html):
  super().__init__(convert_charrefs=True);self.elements=[];self.feed(html);self.close()
 def handle_starttag(self,tag,attrs):
  if tag.startswith('pl-'):
   if len({key for key,_ in attrs})!=len(attrs):raise JobError('Ambiguous native control attributes')
   self.elements.append((tag,dict(attrs)))


class EditorStarters(HTMLParser):
 def __init__(self,html):
  super().__init__(convert_charrefs=True);self.values=[];self.current=None;self.feed(html);self.close()
  if self.current is not None:raise JobError('Unclosed manual editor')
 def handle_starttag(self,tag,attrs):
  if self.current is not None:raise JobError('Manual editor starter must be escaped text')
  if tag=='pl-file-editor':
   self.current=[];self.values.append((dict(attrs).get('file-name'),self.current))
 def handle_endtag(self,tag):
  if self.current is not None and tag!='pl-file-editor':raise JobError('Manual editor starter must be escaped text')
  if tag=='pl-file-editor':self.current=None
 def handle_data(self,data):
  if self.current is not None:self.current.append(data)


def upload_values(attrs,key,paths=True):
 if key not in attrs:return []
 value=attrs[key]
 if not isinstance(value,str):raise JobError('Empty native upload attribute')
 values=[part.strip() for part in value.split(',')]
 if not values or any(not part or (paths and not relative_name(part)) for part in values) or len(set(values))!=len(values):raise JobError('Invalid native upload names/patterns')
 return values


def classification(delivery):
 if not isinstance(delivery,dict) or type(delivery.get('schemaVersion')) is not int or delivery.get('schemaVersion') != 5:raise JobError('Expected functional delivery v5')
 required={'schemaVersion','courseId','bookRoot','questions','gradingPayloads','works','instances','files'}
 if not required<=delivery.keys() or set(delivery)-required-{'candidate'} or not isinstance(delivery.get('courseId'),str) or not re.fullmatch(r'[a-z][a-z0-9-]*',delivery['courseId']):raise JobError('Closed canonical delivery v3 required')
 if not isinstance(delivery['works'],list) or not delivery['works'] or not isinstance(delivery['instances'],dict) or not delivery['instances']:raise JobError('Native work/instance catalog required')
 if 'candidate' in delivery and type(delivery['candidate']) is not bool:raise JobError('Invalid candidate marker')
 questions=delivery.get('questions');bindings=delivery.get('gradingPayloads')
 if not isinstance(questions,list) or not questions or any(not isinstance(q,str) or not re.fullmatch(re.escape(delivery.get('courseId',''))+r'/exr-[a-z0-9][a-z0-9-]*',q) for q in questions) or len(set(questions))!=len(questions):raise JobError('Exact unique nonempty question catalog required')
 if not isinstance(bindings,dict) or set(bindings)!=set(questions):raise JobError('Exact grading binding catalog required')
 methods={};uuids=set()
 for q in questions:
  binding=bindings[q]
  if delivery['schemaVersion']==5:
   from delivery4 import binding4
   if not isinstance(binding,dict):raise JobError('Closed delivery4 binding required')
   if binding.get('kind')!='project':
    method=binding4(binding)
    try:valid_uuid=isinstance(binding['uuid'],str) and str(uuid.UUID(binding['uuid']))==binding['uuid'].lower()
    except (ValueError,TypeError):valid_uuid=False
    if not valid_uuid or binding['uuid'] in uuids:raise JobError('Unique canonical question UUIDs required')
    uuids.add(binding['uuid']);methods[q]=method;continue
   binding={k:v for k,v in binding.items() if k!='kind'}
  if not isinstance(binding,dict) or not {'uuid' ,'grading','submission','sourceRoot'}<=binding.keys():raise JobError('Canonical grading/submission binding required')
  grading=binding['grading'];submission=binding['submission']
  if not isinstance(grading,dict) or set(grading)!={'method'} or grading['method'] not in ('external','mixed','manual'):raise JobError('Explicit canonical grading method required')
  method=grading['method'];allowed={'uuid','grading','submission','sourceRoot'}|({'projectCheck','runtime','sources'} if method!='manual' else set())
  if set(binding)!=allowed:raise JobError('Closed method-specific question binding required')
  if not isinstance(submission,dict) or set(submission)-{'mode','aceMode','layout'} or submission.get('mode') not in ('upload','editor') or submission.get('mode')=='upload' and 'aceMode' in submission:raise JobError('Closed canonical submission required')
  if 'layout' in submission and (submission['mode']!='upload' or submission['layout'] not in ('files','zip','files-or-zip')):raise JobError('Invalid native upload layout')
  if 'aceMode' in submission and (not isinstance(submission['aceMode'],str) or not submission['aceMode']):raise JobError('Invalid editor mode')
  try:valid_uuid=isinstance(binding['uuid'],str) and str(uuid.UUID(binding['uuid']))==binding['uuid'].lower()
  except (ValueError,TypeError,AttributeError):valid_uuid=False
  if not valid_uuid or binding['uuid'] in uuids:raise JobError('Unique canonical question UUIDs required')
  if not relative_name(binding['sourceRoot']):raise JobError('Invalid owner-relative project source root')
  if method!='manual':
   if any(not isinstance(binding[k],str) or not binding[k] for k in ('projectCheck','runtime')) or not isinstance(binding['sources'],list) or not binding['sources']:raise JobError('Automatic source/check binding required')
   targets=set()
   for source in binding['sources']:
    if not isinstance(source,dict) or set(source)!={'projectRelativePath','submissionRelativePath'} or any(not relative_name(source[k]) for k in ('projectRelativePath','submissionRelativePath')) or source['submissionRelativePath'] in targets:raise JobError('Invalid or duplicate automatic source binding')
    targets.add(source['submissionRelativePath'])
  uuids.add(binding['uuid']);methods[q]=method
 return methods


def package_integrity(delivery,native,checks=None):
 native=Path(native);methods=classification(delivery)
 from delivery4 import code_ids,native_proof,seed_proof
 automatic_ids=code_ids(delivery)
 files=delivery.get('files')
 if not isinstance(files,list) or not files or len(set(files))!=len(files):raise JobError('Selected native file paths required')
 for name in files:
  if not relative_name(name):raise JobError('Unsafe selected native path')
  file_bytes(native,name)
 def read(name):
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
   optional_ids={q for slot in slots if slot['assignment']['requirement']=='optional' for q in slot['candidates']}
   for zone,group in groups:
    for question in group.get('alternatives',[group]):
     q=question['id'];covered.add(q);method=methods[q];auto=question.get('autoPoints',group.get('autoPoints',question.get('points',group.get('points'))));manual=question.get('manualPoints',group.get('manualPoints'))
     zero_optional=q in optional_ids and type(auto) in (int,float) and auto==0 and (manual is None or type(manual) in (int,float) and manual==0)
     if not zero_optional and method=='manual' and (auto not in (None,0) or type(manual) not in (int,float) or manual<=0):raise JobError('Manual component mismatch')
     if not zero_optional and method=='mixed' and (type(auto) not in (int,float) or auto<=0 or type(manual) not in (int,float) or manual<=0):raise JobError('Mixed requires both native components')
     if not zero_optional and method=='external' and manual is not None:raise JobError('External cannot hide a manual component')
 if covered!=set(methods):raise JobError('Exact assessment question coverage required')
 facts={}
 for project in (checks or {}).get('projects',[]):
  q=project.get('qualifiedId')
  if q in facts:raise JobError('Duplicate private project binding')
  facts[q]=project
 result=[]
 for q,method in sorted(methods.items()):
  binding=delivery['gradingPayloads'][q];prefix='questions/'+q+'/';question_files={name[len(prefix):] for name in files if name.startswith(prefix)}
  if not question_files:raise JobError('Question has no canonical files')
  folder=safe(native,'questions/'+q);actual=set()
  for path in folder.rglob('*'):
   if path.is_symlink() or not (path.is_dir() or path.is_file()):raise JobError('Unsafe native question tree')
   if path.is_file():actual.add(path.relative_to(folder).as_posix())
  question_files=actual
  info=read(prefix+'info.json');native_schema('infoQuestion.json',info)
  expected_method=binding.get('upstreamGradingMethod', 'Manual' if method=='manual' else 'External')
  if info['uuid']!=binding['uuid'] or info.get('gradingMethod')!=expected_method:raise JobError('Native method/UUID differs from canonical binding')
  question_html=file_bytes(native,prefix+'question.html').decode('utf-8')
  controls=Controls(question_html).elements
  if delivery['schemaVersion']==5 and binding['kind']!='project':
   if q in facts or 'externalGradingOptions' in info:raise JobError('Non-project cannot accept code Job')
   if binding['kind']=='native-answer':
    if info.get('showCorrectAnswer') is not False:raise JobError('Native answer key visibility differs')
    native_proof(q,binding,question_files,controls)
    if info.get('partialCredit') is not (method!='manual'):raise JobError('Native partial-credit policy differs')
    mode='native-answer'
   else:
    if info.get('workspaceOptions')!=binding['submission']['workspaceOptions'] or info.get('singleVariant') is not True or not any(t=='pl-workspace' for t,_ in controls) or any(n.startswith('tests/') or n in ('server.py','server.js','server.ts') for n in question_files):raise JobError('Workspace native controls differ')
    seed_proof(native,prefix,binding);mode='workspace'
   result.append({'qualifiedId':q,'method':method,'uuid':binding['uuid'],'submissionMode':mode})
   continue
  uploads=[attrs for tag,attrs in controls if tag=='pl-file-upload'];editors=[attrs for tag,attrs in controls if tag=='pl-file-editor']
  descriptor=None
  if method!='manual':
   descriptor=read(prefix+'tests/grading-job.json')
   from grading_job import validate
   validate('grading-descriptor',descriptor)
  names=[];optional=[];required_patterns=[];optional_patterns=[]
  for attrs in uploads:
   required=upload_values(attrs,'file-names');extra=upload_values(attrs,'optional-file-names')
   required_globs=upload_values(attrs,'file-patterns',False);optional_globs=upload_values(attrs,'optional-file-patterns',False)
   globs=required_globs+optional_globs
   if not required and not extra and not globs:raise JobError('Native upload input missing or empty')
   names.extend(required);optional.extend(extra);required_patterns.extend(required_globs);optional_patterns.extend(optional_globs)
  if len(set(names+optional))!=len(names+optional):raise JobError('Duplicate native upload name')
  patterns=required_patterns+optional_patterns
  layout=binding['submission'].get('layout')
  mirror='serverFilesQuestion/starter/'
  manual_sources=sorted(name[len(mirror):] for name in question_files if name.startswith(mirror) and name.endswith('.java')) if method=='manual' else []
  if manual_sources:
   if any(not relative_name(name) for name in manual_sources):raise JobError('Unsafe manual Java starter path')
   if len(manual_sources)<=2:
    if binding['submission']['mode']!='editor':raise JobError('One or two manual Java sources require editors')
   else:
    expected_layout='zip' if any('/' in name for name in manual_sources) else 'files'
    expected_names=['solution.zip'] if expected_layout=='zip' else manual_sources
    if binding['submission']['mode']!='upload' or layout!=expected_layout or sorted(names)!=sorted(expected_names) or optional or patterns:raise JobError('Manual Java upload differs from actual starter files')
  if method!='manual':
   extra_policy=descriptor.get('additionalJavaSources');optional_primary=extra_policy is not None and extra_policy.get('primaryRequired',True) is False
   if layout is not None:
    expected_names=[source['submissionRelativePath'] for source in binding['sources']]
    if editors or not uploads:raise JobError('Native upload layout requires upload controls')
    if layout=='files-or-zip':
     if not extra_policy or names or optional!=[extra_policy['archive']] or required_patterns or optional_patterns!=['*.java']:raise JobError('Native free file/ZIP controls differ from layout')
    elif layout=='zip':
     if not extra_policy or names!=[extra_policy['archive']] or optional or patterns:raise JobError('Native ZIP controls differ from layout')
    elif set(names)!=set(expected_names) or optional or patterns:raise JobError('Native fixed files differ from layout')
   elif binding['submission']['mode']=='upload':
    expected_optional=([*[source['submissionRelativePath'] for source in binding['sources'] if '/' not in source['submissionRelativePath']],extra_policy['archive']] if optional_primary else [extra_policy['archive']]) if extra_policy else []
    if patterns or sorted(optional)!=sorted(expected_optional):raise JobError('Native upload optional files differ from declared policy')
  if binding['submission']['mode']=='upload':
   if editors or not uploads:raise JobError('Native upload input missing or empty')
   if method!='manual' and layout is None and set(names)!=(set() if optional_primary else {source['submissionRelativePath'] for source in binding['sources']}):raise JobError('Native upload inputs differ from bound source files')
  else:
   if uploads:raise JobError('Editor cannot include upload controls')
   expected=manual_sources if method=='manual' else [source['submissionRelativePath'] for source in binding['sources']]
   if not editors or len({a.get('file-name') for a in editors})!=len(editors) or {a.get('file-name') for a in editors}!=set(expected):raise JobError('Native editor inputs differ from bound source files')
   if method=='manual':
    if not 1<=len(expected)<=2:raise JobError('Manual editor requires one or two actual Java starter files')
    if any(attrs.get('normalize-to-ascii')!='false' for attrs in editors):raise JobError('Manual editor must preserve UTF-8 source')
    starters=EditorStarters(question_html).values
    if len(starters)!=len(expected):raise JobError('Manual editor starter count differs')
    for name,parts in starters:
     data=file_bytes(native,prefix+mirror+name)
     try:data.decode('utf-8')
     except UnicodeDecodeError as error:raise JobError('Manual editor starter must be UTF-8') from error
     if len(data)>1048576 or b'\0' in data or ''.join(parts).encode('utf-8')!=data:raise JobError('Manual editor starter bytes differ from actual source')
  if not any(name.startswith('clientFilesQuestion/') for name in question_files):raise JobError('Public starter/resource files missing')
  if method=='manual':
   if q in facts or 'externalGradingOptions' in info or any(name.startswith('tests/') or name in ('server.py','server.js','server.ts') for name in question_files) or any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Manual no-grader contract violated')
  else:
   if checks is not None:
    fact=facts.get(q)
    if not fact or not fact.get('check') or fact.get('readiness',{}).get('ready') is False:raise JobError('Automatic question needs ready private check')
    if binding['sourceRoot']!=fact.get('projectRoot') or binding['runtime']!=fact['check'].get('runtime') or binding['projectCheck']!=fact['check'].get('profile') or [(x['projectRelativePath'],x['submissionRelativePath']) for x in binding['sources']]!=[(x['target'],x['name']) for x in fact.get('sources',[])]:raise JobError('Automatic source/check binding differs')
   if descriptor['runtime']!=binding['runtime'] or not info.get('externalGradingOptions',{}).get('image') or not any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Automatic runtime/native control missing')
  result.append({'qualifiedId':q,'method':method,'uuid':binding['uuid'],'submissionMode':binding['submission']['mode']})
 return {'status':'success','questionBindings':result}
