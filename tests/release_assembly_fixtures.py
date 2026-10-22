"""Вымышленные UNIT-образы/тег: реальные локальные Git/bytes, не release evidence."""
from pathlib import Path
import copy,hashlib,importlib.util,io,json,os,subprocess,tarfile
ROOT=Path(__file__).resolve().parents[1]
REPOSITORY='https://github.com/Afonenko-Course-Tools/prairielearn-platform'
IMAGES={'java':'ghcr.io/unit-example/java25-grader@sha256:'+'1'*64,'fish':'ghcr.io/unit-example/fish-git-grader@sha256:'+'2'*64,'community':'ghcr.io/unit-example/prairielearn-community-gateway@sha256:'+'3'*64}
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def git(root,*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',*args],cwd=root,stderr=subprocess.PIPE).decode().strip()
def put(path,value,mode=0o644):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value if isinstance(value,bytes) else value.encode());path.chmod(mode)
def write_json(path,value,mode=0o644):put(path,json.dumps(value,indent=2)+'\n',mode)
class AssemblyFixture:
 def __init__(self,root):
  self.root=Path(root);self.platform=self.root/'platform';self.platform.mkdir();self.assets=self.root/'assets';self.assets.mkdir(mode=0o700)
  # Полная реальная source-unit копия текущего кода; новый owned module указан явно.
  names=[n for n in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0') if n]
  if (ROOT/'tools/release_assembly.py').is_file():names.append('tools/release_assembly.py')
  for n in sorted(set(names)):
   f=ROOT/n;put(self.platform/n,f.read_bytes(),0o755 if f.stat().st_mode&0o111 else 0o644)
  git(self.platform,'init','-q');git(self.platform,'remote','add','origin',REPOSITORY);git(self.platform,'add','-A');git(self.platform,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT source fixture')
  self.commit=git(self.platform,'rev-parse','HEAD');self.tree=git(self.platform,'rev-parse','HEAD^{tree}');git(self.platform,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','tag','-a','v2.3.0','-m','UNIT ONLY not published')
  prep=load('unit_assembly_preparer',ROOT/'tools/prepare_native_toolchain.py');pub=load('unit_assembly_publisher',ROOT/'tools/publish-receipt.py')
  self.lock,_=prep.generated_locks(json.loads((self.platform/'runtime/gradle-jar-v1/toolchain-lock.json').read_bytes()))
  value=prep.baked_view(self.platform,self.lock);value['profiles']['fish-git-v1']=prep._fish_view(self.platform)['profiles']['fish-git-v1'];self.registry=pub.assign_images(value,IMAGES);registry=prep.encode(self.registry)
  receipt={'schemaVersion':2,'sourceCommit':self.commit,'version':'2.3.0','images':IMAGES,'deliverySchemaVersion':3,'resultsSchemaVersion':2,'runtimeProfilesSha256':hashlib.sha256(registry).hexdigest()}
  for name,data in [('published-runtime-profiles.json',registry),('published-toolchain-lock.json',self.lock),('runtime-image.json',prep.encode(receipt))]:put(self.assets/name,data,0o600)
  self.images=json.loads((self.platform/'images.lock.json').read_bytes())
  for key,record in [('java','javaGrader'),('fish','fishGrader'),('community','communityGateway')]:
   self.images[record].update(image=IMAGES[key],sourceCommit=self.commit,version='2.3.0')
   if 'localImage' in self.images[record]:self.images[record]['localImage']=IMAGES[key].split('@')[0]+':2.3.0'
   if 'localImageId' in self.images[record]:self.images[record]['localImageId']='sha256:'+('4' if key=='java' else '5')*64
  self.images['releaseAssembly']={'schema':'pl-platform-release-assets-v1','repository':REPOSITORY,'sourceCommit':self.commit,'sourceTree':self.tree,'version':'2.3.0','tag':'v2.3.0','assets':{n:hashlib.sha256((self.assets/n).read_bytes()).hexdigest() for n in ['runtime-image.json','published-runtime-profiles.json','published-toolchain-lock.json']}}
  write_json(self.assets/'images.lock.json',self.images,0o600)
  put(self.platform/'runtime-profiles.json',registry);put(self.platform/'runtime/gradle-jar-v1/toolchain-lock.json',self.lock)
  self.course=self.root/'course';self.course.mkdir();git(self.course,'init','-q');git(self.course,'remote','add','origin','https://example.invalid/unit-course.git')
  put(self.course/'tasks/_extensions/course-prairielearn/entrypoints/export-course.ts','// UNIT exporter boundary\n');put(self.course/'tasks/projects/demo/student/S.txt','PUBLIC_UNIT\n');put(self.course/'tasks/demo.qmd','PUBLIC CONDITION\n')
  git(self.course,'add','-A');git(self.course,'-c','user.name=UNIT','-c','user.email=unit@example.invalid','commit','-qm','UNIT course')
  self.binary=self.root/'bin';self.binary.mkdir();script='''#!/usr/bin/env python3
import json,pathlib,sys,hashlib,os
sys.path.insert(0,TOOLS)
from delivery_verification import delivery_receipt
from grading_job import digest
out=pathlib.Path(sys.argv[4]);out.mkdir();checks=pathlib.Path(sys.argv[sys.argv.index('--checks-output')+1])
def put(n,v):
 p=out/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(v if isinstance(v,str) else json.dumps(v))
q='demo/exr-manual';uuid='37d79ee7-fd7d-44db-bd45-6587711862a5'
put('infoCourse.json',{'uuid':'4174cd08-ddff-4006-81cc-d7a6b67d3ee0','name':'UNIT','title':'UNIT','timezone':'Europe/Minsk','topics':[{'name':'fixture','color':'gray1','description':'UNIT'}]})
put('questions/'+q+'/info.json',{'uuid':uuid,'type':'v3','title':'UNIT','topic':'fixture','gradingMethod':'Manual','showCorrectAnswer':False})
put('questions/'+q+'/question.html','<pl-file-upload file-patterns="*" optional-file-patterns="*"></pl-file-upload>')
put('questions/'+q+'/clientFilesQuestion/README.md','PUBLIC_UNIT')
put('courseInstances/pilot/infoCourseInstance.json',{'uuid':'b1017718-408e-410a-ae67-b525de725a6d','longName':'UNIT'})
put('courseInstances/pilot/assessments/lab/infoAssessment.json',{'uuid':'9af557f9-c196-46bd-b813-09036235e732','type':'Homework','title':'UNIT','set':'Homework','number':'1','zones':[{'questions':[{'id':q,'autoPoints':0,'manualPoints':100}]}]})
slot='demo/lab/exr-manual'
d={'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'verificationInventoryHash':digest([]),'questions':[q],'gradingPayloads':{q:{'uuid':uuid,'grading':{'method':'manual'},'submission':{'mode':'upload'},'sourceRoot':'projects/demo'}},'works':[{'id':'lab','slots':[{'id':slot,'selection':'fixed','candidates':[q],'assignment':{'requirement':'required','workMode':'individual'}}],'policy':{},'completion':{'schemaVersion':2,'mode':'required-slot-completion','source':'per-slot-results-v2','slotIds':[slot],'requiredSlotIds':[slot],'atLeast':1,'fullyCompletedScore':1}}],'instances':{'pilot':{'works':['lab'],'selfEnrollment':False}},'files':{p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}}
d['deliveryHash']=digest(d);put('delivery.json',d);c={'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[]};checks.write_text(json.dumps(c));put('verification-receipt.json',delivery_receipt(d,out,c,registry=json.loads(pathlib.Path(sys.argv[sys.argv.index('--runtime-registry')+1]).read_bytes())))
if os.environ.get('UNIT_ASSEMBLY_MUTATION'):
 p=pathlib.Path(os.environ['UNIT_ASSEMBLY_MUTATION']);p.write_bytes(p.read_bytes()+b'\\n')
'''
  put(self.binary/'quarto',script.replace('TOOLS',repr(str(ROOT/'tools'))),0o755)
