"""Закрытые data-only bindings v4; пакет и seed никогда не исполняются."""
import hashlib,io,json,re,stat,struct,unicodedata,zipfile,zlib
from grading_job import JobError,digest

def closed(v,keys):
 if not isinstance(v,dict) or set(v)!=set(keys):raise JobError('Closed delivery4 binding required')
def slots(binding):
 values=binding['responseSlots'];kind=binding['answerType']
 if not isinstance(values,list) or not 1<=len(values)<=4096:raise JobError('Native response slots required')
 anchors=set()
 for s in values:
  if not isinstance(s,dict) or not {'name','type','anchor'}<=s.keys() or set(s)-{'name','type','anchor','labelAnchor','ordinal','options'} or s['type'] not in ('manual','numeric','single-choice','matching') or any(not isinstance(s[k],str) or not s[k] for k in ('name','anchor')) or s['anchor'] in anchors:raise JobError('Closed unique native slot required')
  anchors.add(s['anchor'])
  if 'labelAnchor' in s and (not isinstance(s['labelAnchor'],str) or not s['labelAnchor']):raise JobError('Invalid label anchor')
  if 'ordinal' in s and (type(s['ordinal']) is not int or s['ordinal']<0):raise JobError('Invalid ordinal')
  if 'options' in s:
   if not isinstance(s['options'],list) or not s['options']:raise JobError('Invalid matching options')
   for i,o in enumerate(s['options']):
    closed(o,['anchor','ordinal'])
    if not isinstance(o['anchor'],str) or not o['anchor'] or o['ordinal']!=i:raise JobError('Invalid matching option')
   if len({o['anchor'] for o in s['options']})!=len(s['options']):raise JobError('Duplicate matching option')
 if kind in ('manual','numeric'):
  if len(values)!=1 or values[0]['name']!='answer' or values[0]['type']!=kind or set(values[0])!={'name','type','anchor'}:raise JobError('Simple slot shape differs')
 elif kind=='single-choice':
  if len(values)<2 or any(s['name']!='answer' or s['type']!=kind or s.get('ordinal')!=i or set(s)!={'name','type','anchor','ordinal','labelAnchor'} for i,s in enumerate(values)):raise JobError('Choice slot shape differs')
 elif kind=='matching':
  if any(s['name']!='match-'+str(i) or s['type']!=kind or s.get('ordinal')!=i or set(s)!={'name','type','anchor','ordinal','labelAnchor','options'} or s['options']!=values[0]['options'] for i,s in enumerate(values)):raise JobError('Matching slot shape differs')
 elif kind=='multipart':
  if len({s['name'] for s in values})!=len(values) or any(s['type'] not in ('manual','numeric') or set(s)!={'name','type','anchor','labelAnchor'} for s in values):raise JobError('Multipart slot shape differs')
 else:raise JobError('Unknown native answer type')
 types={s['type'] for s in values};method='manual' if types=={'manual'} else 'mixed' if 'manual' in types else 'external'
 if binding['grading']!={'method':method} or binding['upstreamGradingMethod']!=('Manual' if method=='manual' else 'Internal'):raise JobError('Native answer grading/slot combination differs')
 return values

def binding4(v):
 kind=v.get('kind') if isinstance(v,dict) else None
 if kind=='native-answer':
  closed(v,['kind','uuid','grading','answerType','responseSlots','upstreamGradingMethod']);slots(v)
 elif kind=='workspace':
  closed(v,['kind','uuid','grading','sourceRoot','submission','seed','upstreamGradingMethod','singleVariant'])
  from delivery_verification import relative_name
  if v['grading']!={'method':'manual'} or v['upstreamGradingMethod']!='Manual' or v['singleVariant'] is not True or not relative_name(v['sourceRoot']):raise JobError('Workspace must be single manual project')
  closed(v['submission'],['mode','workspaceOptions'])
  o=v['submission']['workspaceOptions']
  if v['submission']['mode']!='workspace' or not isinstance(o,dict) or not {'image','home','port','gradedFiles'}<=o.keys() or set(o)-{'image','home','port','gradedFiles','rewriteUrl','enableNetworking'}:raise JobError('Closed workspace options required')
  if not isinstance(o['image'],str) or not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',o['image']) or not isinstance(o['home'],str) or not re.fullmatch(r'/(?:[a-zA-Z0-9_-]+/?)+',o['home']) or type(o['port']) is not int or not 1024<=o['port']<=65535:raise JobError('Workspace runtime binding differs')
  f=o['gradedFiles'];required={'work/**','work/.git/**','work/.*','explanation.m[d]','.pl-seed/identity.jso[n]'}
  if not isinstance(f,list) or any(not isinstance(x,str) for x in f) or not required<=set(f) or len(f)!=len(set(f)) or any(not relative_name(x) for x in f) or any(k in o and type(o[k]) is not bool for k in ('rewriteUrl','enableNetworking')):raise JobError('Workspace return inventory differs')
  closed(v['seed'],['schema','archive','archiveSha256','manifest','manifestSha256'])
  s=v['seed']
  if s['schema']!='pl-git-workspace-seed-v1' or s['archive']!='workspace/.pl-seed/starter.zip' or s['manifest']!='workspace/.pl-seed/manifest.json' or any(not isinstance(s[k],str) or not re.fullmatch('[a-f0-9]{64}',s[k]) for k in ('archiveSha256','manifestSha256')):raise JobError('Workspace seed binding differs')
 else:raise JobError('Unknown delivery4 kind')
 return v['grading']['method']

def code_ids(delivery):
 from delivery_verification import classification
 return {q for q,m in classification(delivery).items() if m!='manual' and (delivery['schemaVersion']==3 or delivery['gradingPayloads'][q]['kind']=='project')}

def native_proof(q,b,question_files,controls):
 expected=[]
 for s in b['responseSlots']:
  value=('pl-rich-text-editor','file-name',s['name']+'.html') if s['type']=='manual' else ('pl-string-input','answers-name',s['name'])
  if value not in expected:expected.append(value)
 actual=[]
 for tag,attrs in controls:
  if tag in ('pl-string-input','pl-rich-text-editor'):
   key='file-name' if tag=='pl-rich-text-editor' else 'answers-name';actual.append((tag,key,attrs.get(key)))
  elif tag!='pl-question-panel':raise JobError('Native answer contains unbound controls')
  if tag=='pl-string-input' and set(attrs)!={'answers-name','allow-blank'} or tag=='pl-string-input' and attrs.get('allow-blank')!='true' or tag=='pl-rich-text-editor' and set(attrs)!={'file-name','placeholder'}:raise JobError('Native answer control attributes differ')
 if actual!=expected or any('correct' in a for _,a in controls):raise JobError('Native controls differ from public response slots')
 if 'server.py' not in question_files or any(n.startswith('tests/') or n in ('server.js','server.ts') for n in question_files):raise JobError('Native answer cannot contain code Job')
 return {'qualifiedId':q,'uuid':b['uuid'],'answerType':b['answerType'],'responseSlotsHash':digest(b['responseSlots']),'controlsHash':digest(controls),'serverSha256':question_files['server.py']}

def seed_proof(native,prefix,b):
 from delivery_verification import file_bytes,relative_name
 seed=b['seed'];raw=file_bytes(native,prefix+seed['archive']);manifest_raw=file_bytes(native,prefix+seed['manifest'])
 if hashlib.sha256(raw).hexdigest()!=seed['archiveSha256'] or hashlib.sha256(manifest_raw).hexdigest()!=seed['manifestSha256']:raise JobError('Seed bytes differ')
 if len(raw)>64*1024**2 or len(manifest_raw)>2*1024**2:raise JobError('Seed bound exceeded')
 manifest=json.loads(manifest_raw);closed(manifest,['schema','sha256','files'])
 if manifest['schema']!=seed['schema'] or manifest['sha256']!=seed['archiveSha256'] or not isinstance(manifest['files'],list) or not manifest['files']:raise JobError('Seed manifest differs')
 expected={}
 for f in manifest['files']:
  closed(f,['name','sha256'])
  if not relative_name(f['name']) or f['name'] in expected or not isinstance(f['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',f['sha256']):raise JobError('Seed inventory invalid')
  expected[f['name']]=f['sha256']
 entries={};aliases=set();total=0
 try:
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   if not 1<=len(z.infolist())<=4096:raise JobError('Seed count exceeded')
   for f in z.infolist():
    name=f.filename;mode=f.external_attr>>16;alias=unicodedata.normalize('NFC',name).casefold()
    if not relative_name(name) or name in entries or alias in aliases or f.is_dir() or f.flag_bits&1 or stat.S_IFMT(mode) not in (0,stat.S_IFREG) or f.file_size>8*1024**2:raise JobError('Unsafe seed entry')
    total+=f.file_size
    if total>64*1024**2:raise JobError('Expanded seed bound exceeded')
    data=z.read(f);entries[name]=data;aliases.add(alias)
 except (zipfile.BadZipFile,RuntimeError) as e:raise JobError('Invalid seed ZIP') from e
 if {n:hashlib.sha256(v).hexdigest() for n,v in entries.items()}!=expected:raise JobError('Exact seed inventory differs')
 # Public materialization copies must agree byte-for-byte with seed entries.
 for n,data in entries.items():
  if '/.git/' not in '/'+n and file_bytes(native,prefix+'clientFilesQuestion/starter/'+n)!=data:raise JobError('Seed/source common file differs')
 if file_bytes(native,prefix+'clientFilesQuestion/starter.zip')!=raw:raise JobError('Workspace public ZIP differs from seed')
 required={'work/.git/HEAD','work/.git/config','work/.git/index','work/README.md','work/notes.txt'}
 if not required<=entries.keys() or entries['work/.git/HEAD']!=b'ref: refs/heads/main\n':raise JobError('Initial Git main state required')
 import configparser
 config=configparser.ConfigParser(interpolation=None)
 try:config.read_string(entries['work/.git/config'].decode())
 except (ValueError,configparser.Error) as e:raise JobError('Invalid Git config') from e
 if set(config.sections())!={'core'} or set(config['core'])-{'repositoryformatversion','filemode','bare','logallrefupdates'} or config['core'].get('bare')!='false' or config['core'].get('repositoryformatversion')!='0':raise JobError('Unsafe initial Git config')
 if any(n.startswith('work/.git/refs/') and n!='work/.git/refs/heads/main' or n in ('work/.git/commondir','work/.git/objects/info/alternates','work/.git/packed-refs') for n in entries):raise JobError('External Git state refused')
 ref=entries.get('work/.git/refs/heads/main',b'').decode().strip()
 if not re.fullmatch('[a-f0-9]{40}',ref):raise JobError('Initial Git commit missing')
 seen=set()
 def obj(oid,kind):
  name='work/.git/objects/'+oid[:2]+'/'+oid[2:];data=entries.get(name)
  if data is None:raise JobError('Git object closure missing')
  d=zlib.decompressobj();value=d.decompress(data,8*1024**2+1)
  if len(value)>8*1024**2 or not d.eof or d.unused_data or hashlib.sha1(value).hexdigest()!=oid:raise JobError('Git object identity differs')
  head,body=value.split(b'\0',1)
  if head!=kind.encode()+b' '+str(len(body)).encode():raise JobError('Git object kind/length differs')
  seen.add(name);return body
 commit=obj(ref,'commit');headers,message=commit.split(b'\n\n',1)
 if message.strip()!=b'A' or any(x.startswith(b'parent ') for x in headers.splitlines()) or not re.fullmatch(b'tree [a-f0-9]{40}',headers.splitlines()[0]):raise JobError('Initial Git A required')
 tracked={}
 def tree(oid,path=''):
  value=obj(oid,'tree');offset=0
  while offset<len(value):
   end=value.index(b'\0',offset);mode,name=value[offset:end].split(b' ',1);oid=value[end+1:end+21].hex();offset=end+21;name=path+name.decode()
   if not relative_name(name):raise JobError('Unsafe Git tree path')
   if mode==b'40000':tree(oid,name+'/')
   elif mode in (b'100644',b'100755'):
    blob=obj(oid,'blob')
    if entries.get('work/'+name)!=blob or name in tracked:raise JobError('Git worktree differs')
    tracked[name]=(int(mode,8),oid)
   else:raise JobError('Unsafe Git tree mode')
 tree(headers.splitlines()[0][5:].decode())
 if {n[5:] for n in entries if n.startswith('work/') and not n.startswith('work/.git/')}!=set(tracked):raise JobError('Untracked initial worktree files')
 if not tracked or any(n.startswith('work/.git/objects/') and n not in seen for n in entries):raise JobError('Unbound Git objects')
 index=entries['work/.git/index']
 if len(index)<32 or index[:4]!=b'DIRC' or struct.unpack('>I',index[4:8])[0]!=2 or hashlib.sha1(index[:-20]).digest()!=index[-20:]:raise JobError('Invalid Git index')
 count=struct.unpack('>I',index[8:12])[0];offset=12;indexed={};previous=None
 if count!=len(tracked):raise JobError('Git index/tree entry count differs')
 for _ in range(count):
  start=offset
  if offset+62>len(index)-20:raise JobError('Truncated Git index')
  mode=struct.unpack('>I',index[offset+24:offset+28])[0];oid=index[offset+40:offset+60].hex();flags=struct.unpack('>H',index[offset+60:offset+62])[0]
  try:end=index.index(b'\0',offset+62,len(index)-20);raw_name=index[offset+62:end];name=raw_name.decode('utf-8')
  except (ValueError,UnicodeError) as e:raise JobError('Invalid Git index pathname') from e
  if flags&0xf000 or (flags&0xfff)!=min(len(raw_name),0xfff) or not relative_name(name) or name in indexed or previous is not None and raw_name<=previous:raise JobError('Unsafe Git index entry')
  previous=raw_name;indexed[name]=(mode,oid);offset=start+((end+1-start+7)//8)*8
  if offset>len(index)-20:raise JobError('Truncated Git index entry')
 if indexed!=tracked:raise JobError('Git index/tree differs')
 return {'archiveSha256':seed['archiveSha256'],'manifestSha256':seed['manifestSha256'],'filesHash':digest(expected),'initialCommit':ref}


def internal_proof(delivery,native):
 from delivery_verification import Controls,file_bytes
 values=[]
 for q in sorted(delivery['questions']):
  b=delivery['gradingPayloads'][q]
  if b['kind']!='native-answer':continue
  prefix='questions/'+q+'/'
  files={n[len(prefix):]:sha for n,sha in delivery['files'].items() if n.startswith(prefix)}
  values.append(native_proof(q,b,files,Controls(file_bytes(native,prefix+'question.html').decode()).elements))
 return {'kind':'native-answer-package-v1','deliveryHash':delivery['deliveryHash'],'bindings':values,'inventoryHash':digest(values)}


def workspace_image_authority(delivery,registry):
 images={b['submission']['workspaceOptions']['image'] for b in delivery['gradingPayloads'].values() if b['kind']=='workspace'}
 if not images:return
 if not isinstance(registry,dict) or registry.get('schemaVersion')!=2:raise JobError('Workspace image authority unqualified; package proof is not image qualification')
 closed(registry,['schemaVersion','profiles','workspaceImages'])
 authority=registry['workspaceImages']
 if not isinstance(authority,dict) or set(authority)!={'sp-git-workspace-v1'}:raise JobError('Workspace image authority unqualified')
 closed(authority['sp-git-workspace-v1'],['image']);image=authority['sp-git-workspace-v1']['image']
 if not isinstance(image,str) or not re.fullmatch(r'ghcr\.io/[a-z0-9-]+/sp-git-workspace@sha256:[a-f0-9]{64}',image) or images!={image}:raise JobError('Workspace exact qualified image differs')
