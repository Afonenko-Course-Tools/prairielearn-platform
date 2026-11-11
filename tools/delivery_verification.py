"""Проверка actual native пакета; не исполняет и не оценивает ручной ответ."""
import json,re,stat,uuid
from html.parser import HTMLParser
from pathlib import Path
import jsonschema
from typing import Literal, Protocol, TypeAlias, TypeGuard, TypedDict, runtime_checkable
from collections.abc import Mapping
from json_boundary import is_object, is_list, json_object, json_value
from delivery_types import GradingMethod, NativeControl
from grading_job import ROOT,JobError,safe
from native_course_options import integer_manual_points_schema

def relative_name(value: object) -> TypeGuard[str]:
 return isinstance(value,str) and bool(value) and not value.startswith('/') and not re.match(r'^[A-Za-z]:',value) and not re.search(r'[\x00-\x1f\x7f]',value) and '\\' not in value and not any(part in ('','.','..') for part in value.split('/'))
def file_bytes(root: str | Path, name: str) -> bytes:
 try:
  path=safe(root,name)
  if not stat.S_ISREG(path.lstat().st_mode):raise JobError('Native package requires regular files')
  return path.read_bytes()
 except OSError as error:raise JobError('Missing native package file: '+name) from error

@runtime_checkable
class _NativeSchemaValidate(Protocol):
 def __call__(self, instance: object) -> None: ...


def native_schema(name: str, value: object) -> None:
 folder=ROOT/'schemas/native-upstream'
 try:
  schema=json_object(json.loads(file_bytes(folder,name)))
  if name=='infoCourse.json':schema=integer_manual_points_schema(schema)
  validate_value: object=getattr(jsonschema.Draft7Validator(schema),'validate')
  if not isinstance(validate_value,_NativeSchemaValidate):raise JobError('Native JSON schema validator unavailable')
  validate_value(json_value(value))
 except jsonschema.ValidationError as error:raise JobError('Invalid native '+name+': '+error.message) from error

class Controls(HTMLParser):
 def __init__(self,html: str) -> None:
  super().__init__(convert_charrefs=True);self.elements: list[NativeControl]=[];self.feed(html);self.close()
 def handle_starttag(self,tag: str,attrs: list[tuple[str,str|None]]) -> None:
  if tag.startswith('pl-'):
   if len({key for key,_ in attrs})!=len(attrs):raise JobError('Ambiguous native control attributes')
   self.elements.append((tag,dict(attrs)))


class EditorStarters(HTMLParser):
 def __init__(self,html: str) -> None:
  super().__init__(convert_charrefs=True);self.values: list[tuple[str|None,list[str]]]=[];self.current: list[str]|None=None;self.feed(html);self.close()
  if self.current is not None:raise JobError('Unclosed manual editor')
 def handle_starttag(self,tag: str,attrs: list[tuple[str,str|None]]) -> None:
  if self.current is not None:raise JobError('Manual editor starter must be escaped text')
  if tag=='pl-file-editor':
   self.current=[];self.values.append((dict(attrs).get('file-name'),self.current))
 def handle_endtag(self,tag: str) -> None:
  if self.current is not None and tag!='pl-file-editor':raise JobError('Manual editor starter must be escaped text')
  if tag=='pl-file-editor':self.current=None
 def handle_data(self,data: str) -> None:
  if self.current is not None:self.current.append(data)


def upload_values(attrs: Mapping[str,str|None], key: str, paths: bool = True) -> list[str]:
 if key not in attrs:return []
 value=attrs[key]
 if not isinstance(value,str):raise JobError('Empty native upload attribute')
 values=[part.strip() for part in value.split(',')]
 if not values or any(not part or (paths and not relative_name(part)) for part in values) or len(set(values))!=len(values):raise JobError('Invalid native upload names/patterns')
 return values


def _object(value: object) -> TypeGuard[dict[str,object]]:
 return is_object(value) and all(isinstance(key,str) for key in value)


def _strings(value: object) -> TypeGuard[list[str]]:
 return is_list(value) and all(isinstance(item,str) for item in value)


def _record(value: object, message: str) -> dict[str,object]:
 if not _object(value):raise JobError(message)
 return value


def _record_list(value: object) -> TypeGuard[list[dict[str,object]]]:
 return is_list(value) and all(_object(item) for item in value)


def _records(value: object, message: str) -> list[dict[str,object]]:
 if not _record_list(value):raise JobError(message)
 return value


def _text(value: object, message: str) -> str:
 if not isinstance(value,str):raise JobError(message)
 return value


def _texts(value: object, message: str) -> list[str]:
 if not _strings(value):raise JobError(message)
 return value


def _number(value: object) -> TypeGuard[int|float]:
 return type(value) in (int,float)


ProjectSubmissionMode: TypeAlias=Literal['upload','editor']
PackageSubmissionMode: TypeAlias=Literal['upload','editor','native-answer','workspace']


def _project_submission_mode(value: object) -> ProjectSubmissionMode:
 if value=='upload':return 'upload'
 if value=='editor':return 'editor'
 raise JobError('Closed canonical submission required')


class PackageQuestionBinding(TypedDict):
 qualifiedId: str
 method: GradingMethod
 uuid: str
 submissionMode: PackageSubmissionMode


class PackageIntegrityResult(TypedDict):
 status: Literal['success']
 questionBindings: list[PackageQuestionBinding]


def _grading_method(value: object) -> GradingMethod:
 if value=='external':return 'external'
 if value=='mixed':return 'mixed'
 if value=='manual':return 'manual'
 raise JobError('Explicit canonical grading method required')


def classification(delivery: object) -> dict[str,GradingMethod]:
 if not _object(delivery) or type(delivery.get('schemaVersion')) is not int or delivery.get('schemaVersion')!=5:raise JobError('Expected functional delivery v5')
 required={'schemaVersion','courseId','bookRoot','questions','gradingPayloads','works','instances','files'}
 course_id=delivery.get('courseId')
 if not required<=delivery.keys() or set(delivery)-required-{'candidate'} or not isinstance(course_id,str) or not re.fullmatch(r'[a-z][a-z0-9-]*',course_id):raise JobError('Closed canonical delivery v3 required')
 works,instances=delivery['works'],delivery['instances']
 if not is_list(works) or not works or not _object(instances) or not instances:raise JobError('Native work/instance catalog required')
 if 'candidate' in delivery and type(delivery['candidate']) is not bool:raise JobError('Invalid candidate marker')
 questions=delivery['questions'];bindings=delivery['gradingPayloads']
 if not _strings(questions) or not questions or any(not re.fullmatch(re.escape(course_id)+r'/exr-[a-z0-9][a-z0-9-]*',question) for question in questions) or len(set(questions))!=len(questions):raise JobError('Exact unique nonempty question catalog required')
 if not _object(bindings) or set(bindings)!=set(questions):raise JobError('Exact grading binding catalog required')
 methods: dict[str,GradingMethod]={};uuids: set[str]=set()
 for question in questions:
  binding=bindings[question]
  from delivery4 import binding4
  if not _object(binding):raise JobError('Closed delivery4 binding required')
  if binding.get('kind')!='project':
   method=binding4(binding)
   question_uuid=binding['uuid']
   if not isinstance(question_uuid,str):raise JobError('Unique canonical question UUIDs required')
   try:valid_uuid=str(uuid.UUID(question_uuid))==question_uuid.lower()
   except (ValueError,TypeError):valid_uuid=False
   if not valid_uuid or question_uuid in uuids:raise JobError('Unique canonical question UUIDs required')
   uuids.add(question_uuid);methods[question]=method;continue
  binding={key:value for key,value in binding.items() if key!='kind'}
  if not {'uuid','grading','submission','sourceRoot'}<=binding.keys():raise JobError('Canonical grading/submission binding required')
  grading=binding['grading'];submission=binding['submission']
  if not _object(grading) or set(grading)!={'method'}:raise JobError('Explicit canonical grading method required')
  method=_grading_method(grading['method'])
  allowed: set[str]={'uuid','grading','submission','sourceRoot'}|({'projectCheck','runtime','sources'} if method!='manual' else set[str]())
  if set(binding)!=allowed:raise JobError('Closed method-specific question binding required')
  if not _object(submission) or set(submission)-{'mode','aceMode','layout'} or submission.get('mode') not in ('upload','editor') or submission.get('mode')=='upload' and 'aceMode' in submission:raise JobError('Closed canonical submission required')
  if 'layout' in submission and (submission['mode']!='upload' or submission['layout'] not in ('files','zip','files-or-zip')):raise JobError('Invalid native upload layout')
  if 'aceMode' in submission and (not isinstance(submission['aceMode'],str) or not submission['aceMode']):raise JobError('Invalid editor mode')
  question_uuid=binding['uuid']
  if not isinstance(question_uuid,str):raise JobError('Unique canonical question UUIDs required')
  try:valid_uuid=str(uuid.UUID(question_uuid))==question_uuid.lower()
  except (ValueError,TypeError,AttributeError):valid_uuid=False
  if not valid_uuid or question_uuid in uuids:raise JobError('Unique canonical question UUIDs required')
  if not relative_name(binding['sourceRoot']):raise JobError('Invalid owner-relative project source root')
  if method!='manual':
   sources=binding['sources']
   if any(not isinstance(binding[key],str) or not binding[key] for key in ('projectCheck','runtime')) or not is_list(sources) or not sources:raise JobError('Automatic source/check binding required')
   targets: set[str]=set()
   for source in sources:
    if not _object(source) or set(source)!={'projectRelativePath','submissionRelativePath'}:raise JobError('Invalid or duplicate automatic source binding')
    source_path,target=source['projectRelativePath'],source['submissionRelativePath']
    if not relative_name(source_path) or not relative_name(target) or target in targets:raise JobError('Invalid or duplicate automatic source binding')
    targets.add(target)
  uuids.add(question_uuid);methods[question]=method
 return methods


def package_integrity(delivery: object, native: str | Path, checks: object = None) -> PackageIntegrityResult:
 native=Path(native);methods=classification(delivery)
 delivery=_record(delivery,'Expected functional delivery v5')
 from delivery4 import code_ids,native_proof,seed_proof
 code_ids(delivery)
 files=delivery.get('files')
 if not _strings(files) or not files or len(set(files))!=len(files):raise JobError('Selected native file paths required')
 for name in files:
  if not relative_name(name):raise JobError('Unsafe selected native path')
  file_bytes(native,name)
 def read(name: str) -> object:
  try:return json.loads(file_bytes(native,name))
  except ValueError as error:raise JobError('Invalid native JSON') from error
 native_schema('infoCourse.json',read('infoCourse.json'))
 for name in files:
  if re.fullmatch(r'courseInstances/[^/]+/infoCourseInstance.json',name):native_schema('infoCourseInstance.json',read(name))
 covered: set[str]=set()
 work_rows=_records(delivery['works'],'Unique canonical work identities required')
 works: dict[str,dict[str,object]]={}
 for work in work_rows:
  work_id=work.get('id')
  if not isinstance(work_id,str) or not re.fullmatch(r'[a-z][a-z0-9-]*',work_id) or work_id in works:raise JobError('Unique canonical work identities required')
  works[work_id]=work
 instances=_record(delivery['instances'],'Exact canonical instance work catalog required')
 course_id=_text(delivery['courseId'],'Expected functional delivery v5')
 for instance,catalog_value in instances.items():
  catalog=_record(catalog_value,'Exact canonical instance work catalog required')
  instance_works=catalog.get('works')
  if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',instance) or set(catalog)!={'works','selfEnrollment'} or type(catalog['selfEnrollment']) is not bool or not _strings(instance_works) or not instance_works or len(set(instance_works))!=len(instance_works) or any(work not in works for work in instance_works):raise JobError('Exact canonical instance work catalog required')
  instance_path='courseInstances/'+instance+'/infoCourseInstance.json'
  if instance_path not in files:raise JobError('Native instance metadata missing')
  for work_id in instance_works:
   work=works[work_id];name='courseInstances/'+instance+'/assessments/'+work_id+'/infoAssessment.json'
   assessment_value=read(name);native_schema('infoAssessment.json',assessment_value)
   assessment=_record(assessment_value,'Invalid native assessment object')
   if set(work)-{'id','slots','policy','completion','relatedExercise'} or not {'id','slots','policy','completion'}<=set(work) or not is_object(work['policy']):raise JobError('Closed canonical work required')
   slots=_records(work.get('slots'),'Canonical nonempty work slots required')
   if not slots:raise JobError('Canonical nonempty work slots required')
   zones=_records(assessment['zones'],'Invalid native assessment zones')
   groups=[(zone,group) for zone in zones for group in _records(zone['questions'],'Invalid native assessment questions')]
   used: set[int]=set();slot_ids: set[str]=set();candidates: set[str]=set()
   for slot in slots:
    slot_id=slot.get('id')
    if set(slot)!={'id','selection','candidates','assignment'} or not isinstance(slot_id,str) or slot_id in slot_ids or not slot_id.startswith(course_id+'/'+work_id+'/'):raise JobError('Canonical closed slot identity required')
    assignment=_record(slot['assignment'],'Closed canonical slot assignment required')
    if not {'requirement','workMode'}<=set(assignment) or set(assignment)-{'requirement','workMode','stage'} or assignment['requirement'] not in ('required','optional') or assignment['workMode'] not in ('individual','pair','group') or 'stage' in assignment and assignment['stage'] not in ('demonstration','classroom','homework'):raise JobError('Closed canonical slot assignment required')
    slot_ids.add(slot_id);pool=slot['candidates'];selection=slot['selection']
    if selection not in ('fixed','random','choice') or not _strings(pool) or not pool or len(set(pool))!=len(pool) or any(q not in methods or q in candidates for q in pool):raise JobError('Invalid canonical candidate pool')
    if selection=='fixed' and (len(pool)!=1 or slot_id.split('/')[-1]!=pool[0].split('/')[-1]) or selection!='fixed' and (len(pool)<2 or not re.fullmatch(r'alt-[a-z0-9][a-z0-9-]*',slot_id.split('/')[-1])):raise JobError('Invalid canonical slot selection')
    if selection=='choice':
     if assignment.get('requirement')!='required':raise JobError('Choice must be required')
     matches=[(i,zone,group) for i,(zone,group) in enumerate(groups) if 'alternatives' not in group and group.get('id') in pool]
     if len(matches)!=len(pool) or len({_text(group['id'],'Invalid native question id') for _,_,group in matches})!=len(pool) or len({id(zone) for _,zone,_ in matches})!=1:raise JobError('Actual choice candidates must share one complete zone')
     zone=matches[0][1]
     if zone.get('bestQuestions')!=1 or 'numberChoose' in zone or len(_records(zone['questions'],'Invalid native assessment questions'))!=len(pool) or any('numberChoose' in group or i in used for i,_,group in matches):raise JobError('Choice zone must expose all candidates with bestQuestions one')
     used.update(i for i,_,_ in matches)
    else:
     matches=[(i,zone,group) for i,(zone,group) in enumerate(groups) if sorted(_text(q['id'],'Invalid native question id') for q in _records(group.get('alternatives',[group]),'Invalid native question alternatives'))==sorted(pool)]
     if len(matches)!=1:raise JobError('Actual native group differs from canonical slot')
     i,zone,group=matches[0]
     if i in used or 'bestQuestions' in zone or 'numberChoose' in zone or selection=='random' and group.get('numberChoose')!=1 or selection=='fixed' and ('alternatives' in group or group.get('numberChoose',1)!=1):raise JobError('Actual fixed/random group selection differs')
     used.add(i)
    candidates.update(pool)
   if used!=set(range(len(groups))):raise JobError('Unbound native assessment group')
   completion=_record(work['completion'],'Canonical completion differs from native slot catalog')
   ordered=[_text(slot['id'],'Canonical closed slot identity required') for slot in slots]
   required=[_text(slot['id'],'Canonical closed slot identity required') for slot in slots if _record(slot['assignment'],'Closed canonical slot assignment required')['requirement']=='required']
   at_least=completion.get('atLeast')
   if set(completion)!={'schemaVersion','mode','source','slotIds','requiredSlotIds','atLeast','fullyCompletedScore'} or type(completion['schemaVersion']) is not int or completion['schemaVersion']!=2 or completion['mode']!='required-slot-completion' or completion['source']!='per-slot-results-v2' or type(completion['fullyCompletedScore']) is not int or completion['fullyCompletedScore']!=1 or completion['slotIds']!=ordered or completion['requiredSlotIds']!=required or type(at_least) is not int or not 1<=at_least<=len(required):raise JobError('Canonical completion differs from native slot catalog')
   optional_ids={q for slot in slots if _record(slot['assignment'],'Closed canonical slot assignment required')['requirement']=='optional' for q in _texts(slot['candidates'],'Invalid canonical candidate pool')}
   for zone,group in groups:
    for question in _records(group.get('alternatives',[group]),'Invalid native question alternatives'):
     q=_text(question['id'],'Invalid native question id');covered.add(q);method=methods[q];auto=question.get('autoPoints',group.get('autoPoints',question.get('points',group.get('points'))));manual=question.get('manualPoints',group.get('manualPoints'))
     zero_optional=q in optional_ids and _number(auto) and auto==0 and (manual is None or _number(manual) and manual==0)
     if not zero_optional and method=='manual' and (auto not in (None,0) or not _number(manual) or manual<=0):raise JobError('Manual component mismatch')
     if not zero_optional and method=='mixed' and (not _number(auto) or auto<=0 or not _number(manual) or manual<=0):raise JobError('Mixed requires both native components')
     if not zero_optional and method=='external' and manual is not None:raise JobError('External cannot hide a manual component')
 facts: dict[str,dict[str,object]]={}
 if covered!=set(methods):raise JobError('Exact assessment question coverage required')
 private_checks: dict[str,object]={} if checks is None else _record(checks,'Invalid private check catalog')
 for project in _records(private_checks.get('projects',[]),'Invalid private project binding'):
  q=_text(project.get('qualifiedId'),'Invalid private project binding')
  if q in facts:raise JobError('Duplicate private project binding')
  facts[q]=project
 bindings=_record(delivery['gradingPayloads'],'Exact grading binding catalog required')
 result: list[PackageQuestionBinding]=[]
 for q,method in sorted(methods.items()):
  binding=_record(bindings[q],'Closed canonical grading binding required');question_uuid=_text(binding['uuid'],'Unique canonical question UUIDs required')
  prefix='questions/'+q+'/';question_files={name[len(prefix):] for name in files if name.startswith(prefix)}
  if not question_files:raise JobError('Question has no canonical files')
  folder=safe(native,'questions/'+q);actual: set[str]=set()
  for path in folder.rglob('*'):
   if path.is_symlink() or not (path.is_dir() or path.is_file()):raise JobError('Unsafe native question tree')
   if path.is_file():actual.add(path.relative_to(folder).as_posix())
  question_files=actual
  info_value=read(prefix+'info.json');native_schema('infoQuestion.json',info_value)
  info=_record(info_value,'Invalid native question metadata')
  expected_method=binding.get('upstreamGradingMethod', 'Manual' if method=='manual' else 'External')
  if info['uuid']!=question_uuid or info.get('gradingMethod')!=expected_method:raise JobError('Native method/UUID differs from canonical binding')
  question_html=file_bytes(native,prefix+'question.html').decode('utf-8')
  controls=Controls(question_html).elements
  if delivery['schemaVersion']==5 and binding['kind']!='project':
   if q in facts or 'externalGradingOptions' in info:raise JobError('Non-project cannot accept code Job')
   mode: PackageSubmissionMode
   if binding['kind']=='native-answer':
    if info.get('showCorrectAnswer') is not False:raise JobError('Native answer key visibility differs')
    native_proof(q,binding,question_files,controls)
    if info.get('partialCredit') is not (method!='manual'):raise JobError('Native partial-credit policy differs')
    mode='native-answer'
   else:
    submission=_record(binding['submission'],'Closed workspace options required')
    if info.get('workspaceOptions')!=submission['workspaceOptions'] or info.get('singleVariant') is not True or not any(t=='pl-workspace' for t,_ in controls) or any(n.startswith('tests/') or n in ('server.py','server.js','server.ts') for n in question_files):raise JobError('Workspace native controls differ')
    seed_proof(native,prefix,binding);mode='workspace'
   result.append({'qualifiedId':q,'method':method,'uuid':question_uuid,'submissionMode':mode})
   continue
  submission=_record(binding['submission'],'Closed canonical submission required')
  submission_mode=_project_submission_mode(submission['mode'])
  sources: list[dict[str,object]]=[] if method=='manual' else _records(binding['sources'],'Invalid automatic source binding')
  uploads=[attrs for tag,attrs in controls if tag=='pl-file-upload'];editors=[attrs for tag,attrs in controls if tag=='pl-file-editor']
  descriptor: dict[str,object] | None=None
  if method!='manual':
   descriptor_value=read(prefix+'tests/grading-job.json')
   from grading_job import validate
   validate('grading-descriptor',descriptor_value)
   descriptor=_record(descriptor_value,'Invalid grading descriptor')
  names: list[str]=[];optional: list[str]=[];required_patterns: list[str]=[];optional_patterns: list[str]=[]
  for attrs in uploads:
   required=upload_values(attrs,'file-names');extra=upload_values(attrs,'optional-file-names')
   required_globs=upload_values(attrs,'file-patterns',False);optional_globs=upload_values(attrs,'optional-file-patterns',False)
   globs=required_globs+optional_globs
   if not required and not extra and not globs:raise JobError('Native upload input missing or empty')
   names.extend(required);optional.extend(extra);required_patterns.extend(required_globs);optional_patterns.extend(optional_globs)
  if len(set(names+optional))!=len(names+optional):raise JobError('Duplicate native upload name')
  patterns=required_patterns+optional_patterns
  layout=submission.get('layout')
  mirror='serverFilesQuestion/starter/'
  manual_sources: list[str]=sorted(name[len(mirror):] for name in question_files if name.startswith(mirror) and name.endswith('.java')) if method=='manual' else []
  if manual_sources:
   if any(not relative_name(name) for name in manual_sources):raise JobError('Unsafe manual Java starter path')
   if len(manual_sources)<=2:
    if submission_mode!='editor':raise JobError('One or two manual Java sources require editors')
   else:
    expected_layout='zip' if any('/' in name for name in manual_sources) else 'files'
    expected_names=['solution.zip'] if expected_layout=='zip' else manual_sources
    if submission_mode!='upload' or layout!=expected_layout or sorted(names)!=sorted(expected_names) or optional or patterns:raise JobError('Manual Java upload differs from actual starter files')
  optional_primary=False
  if method!='manual':
   if descriptor is None:raise JobError('Invalid grading descriptor')
   policy_value=descriptor.get('additionalJavaSources')
   extra_policy=None if policy_value is None else _record(policy_value,'Invalid additional source policy')
   optional_primary=extra_policy is not None and extra_policy.get('primaryRequired',True) is False
   if layout is not None:
    expected_names=[_text(source['submissionRelativePath'],'Invalid automatic source binding') for source in sources]
    if editors or not uploads:raise JobError('Native upload layout requires upload controls')
    if layout=='files-or-zip':
     if not extra_policy or names or optional!=[extra_policy['archive']] or required_patterns or optional_patterns!=['*.java']:raise JobError('Native free file/ZIP controls differ from layout')
    elif layout=='zip':
     if not extra_policy or names!=[extra_policy['archive']] or optional or patterns:raise JobError('Native ZIP controls differ from layout')
    elif set(names)!=set(expected_names) or optional or patterns:raise JobError('Native fixed files differ from layout')
   elif submission_mode=='upload':
    expected_optional: list[str]=([*[_text(source['submissionRelativePath'],'Invalid automatic source binding') for source in sources if '/' not in _text(source['submissionRelativePath'],'Invalid automatic source binding')],_text(extra_policy['archive'],'Invalid additional source policy')] if optional_primary else [_text(extra_policy['archive'],'Invalid additional source policy')]) if extra_policy else []
    if patterns or sorted(optional)!=sorted(expected_optional):raise JobError('Native upload optional files differ from declared policy')
  if submission_mode=='upload':
   if editors or not uploads:raise JobError('Native upload input missing or empty')
   if method!='manual' and layout is None and set(names)!=(set[str]() if optional_primary else {_text(source['submissionRelativePath'],'Invalid automatic source binding') for source in sources}):raise JobError('Native upload inputs differ from bound source files')
  else:
   if uploads:raise JobError('Editor cannot include upload controls')
   expected=manual_sources if method=='manual' else [_text(source['submissionRelativePath'],'Invalid automatic source binding') for source in sources]
   if not editors or len({a.get('file-name') for a in editors})!=len(editors) or {a.get('file-name') for a in editors}!=set(expected):raise JobError('Native editor inputs differ from bound source files')
   if method=='manual':
    if not 1<=len(expected)<=2:raise JobError('Manual editor requires one or two actual Java starter files')
    if any(attrs.get('normalize-to-ascii')!='false' for attrs in editors):raise JobError('Manual editor must preserve UTF-8 source')
    starters=EditorStarters(question_html).values
    if len(starters)!=len(expected):raise JobError('Manual editor starter count differs')
    for name,parts in starters:
     data=file_bytes(native,prefix+mirror+_text(name,'Native editor inputs differ from bound source files'))
     try:data.decode('utf-8')
     except UnicodeDecodeError as error:raise JobError('Manual editor starter must be UTF-8') from error
     if len(data)>1048576 or b'\0' in data or ''.join(parts).encode('utf-8')!=data:raise JobError('Manual editor starter bytes differ from actual source')
  if not any(name.startswith('clientFilesQuestion/') for name in question_files):raise JobError('Public starter/resource files missing')
  if method=='manual':
   if q in facts or 'externalGradingOptions' in info or any(name.startswith('tests/') or name in ('server.py','server.js','server.ts') for name in question_files) or any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Manual no-grader contract violated')
  else:
   if checks is not None:
    fact=facts.get(q)
    if not fact:raise JobError('Automatic question needs ready private check')
    check=fact.get('check');readiness=_record(fact.get('readiness',{}),'Automatic question needs ready private check')
    if not check or readiness.get('ready') is False:raise JobError('Automatic question needs ready private check')
    check=_record(check,'Automatic question needs ready private check')
    private_sources=_records(fact.get('sources',[]),'Automatic source/check binding differs')
    if binding['sourceRoot']!=fact.get('projectRoot') or binding['runtime']!=check.get('runtime') or binding['projectCheck']!=check.get('profile') or [(_text(x['projectRelativePath'],'Invalid automatic source binding'),_text(x['submissionRelativePath'],'Invalid automatic source binding')) for x in sources]!=[(_text(x['target'],'Invalid private source binding'),_text(x['name'],'Invalid private source binding')) for x in private_sources]:raise JobError('Automatic source/check binding differs')
   if descriptor is None:raise JobError('Invalid grading descriptor')
   external_options=_record(info.get('externalGradingOptions',{}),'Automatic runtime/native control missing')
   if descriptor['runtime']!=binding['runtime'] or not external_options.get('image') or not any(tag=='pl-external-grader-results' for tag,_ in controls):raise JobError('Automatic runtime/native control missing')
  result.append({'qualifiedId':q,'method':method,'uuid':question_uuid,'submissionMode':submission_mode})
 return {'status':'success','questionBindings':result}
