/** Общий deployment descriptor; numeric ID разрешается только native model. */
const keyPattern=/^[a-z][a-z0-9-]*$/;
const closed=(value,fields)=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===[...fields].sort().join(',');
export function validateInstitutionCatalog(catalog) {
 if(!closed(catalog,['schema','institutions'])||catalog.schema!=='pl-institutions-v1'||!catalog.institutions||Array.isArray(catalog.institutions)||typeof catalog.institutions!=='object'||!Object.keys(catalog.institutions).length)throw new Error('Expected pl-institutions-v1 catalog');
 const names=new Set();
 for(const [key,d] of Object.entries(catalog.institutions)) {
  if(!keyPattern.test(key)||!closed(d,['shortName','longName','displayTimezone','uidRegexp']))throw new Error('Closed institution descriptor required');
  for(const field of ['shortName','longName','displayTimezone'])if(typeof d[field]!=='string'||!d[field]||d[field].trim()!==d[field])throw new Error('Explicit institution name/timezone required');
  new Intl.DateTimeFormat('en',{timeZone:d.displayTimezone});
  if(names.has(d.shortName))throw new Error('Duplicate native institution shortName');names.add(d.shortName);
  if(d.uidRegexp!==null) {
   if(typeof d.uidRegexp!=='string'||!d.uidRegexp.startsWith('@')||!d.uidRegexp.endsWith('$')||/(^|[^\\])(?:\\\\)*\./u.test(d.uidRegexp))throw new Error('Invalid native UID regexp');
   new RegExp(d.uidRegexp,'u');
  }
 }
 return catalog.institutions;
}
export function selectRegistryCourse(registry,courseKey,catalog) {
 const descriptors=validateInstitutionCatalog(catalog);
 if(!closed(registry,['schema','courses'])||registry.schema!=='pl-courses-v2'||!Array.isArray(registry.courses)||!registry.courses.length)throw new Error('Bootstrap requires pl-courses-v2 registry');
 const ids=new Set(),mounts=new Set();
 for(const course of registry.courses) {
  if(!closed(course,['id','institution','repository','commit','mount'])||!Object.values(course).every(v=>typeof v==='string')||!keyPattern.test(course.id)||ids.has(course.id)||!/^\/course(?:[2-9]|[1-9][0-9]+)?$/.test(course.mount)||mounts.has(course.mount)||!/^[a-f0-9]{40}$/.test(course.commit))throw new Error('Invalid exact native course pin');
  const url=new URL(course.repository);
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||!url.pathname.slice(1)||/[\s\\%]/.test(course.repository)||course.repository.split('/').includes('..'))throw new Error('Credential-free HTTPS repository required');
  if(!Object.hasOwn(descriptors,course.institution))throw new Error('Unknown institution key');
  ids.add(course.id);mounts.add(course.mount);
 }
 const course=registry.courses.find(c=>c.id===courseKey);
 if(!course)throw new Error('Unknown registry course');return course;
}
export async function resolveInstitution(catalog,key,native) {
 const descriptors=validateInstitutionCatalog(catalog);
 if(!Object.hasOwn(descriptors,key))throw new Error('Unknown institution key');
 const d=descriptors[key];
 return native.withLock('deployment-institution:'+d.shortName,async()=>{
  const rows=(await native.selectAllInstitutions()).filter(i=>i.short_name===d.shortName);
  if(rows.length>1)throw new Error('Ambiguous native institution');
  if(rows.length) {
   const row=rows[0];
   if(row.long_name!==d.longName||row.display_timezone!==d.displayTimezone||row.uid_regexp!==d.uidRegexp)throw new Error('Native institution descriptor differs; explicit operator action required');
   return row.id;
  }
  return await native.insertInstitution({...d});
 });
}
export async function bootstrapNativeCourse({registry,catalog,courseKey,path,info,actorId},native) {
 const record=selectRegistryCourse(registry,courseKey,catalog);
 if(typeof actorId!=='string'||!/^[1-9][0-9]*$/.test(actorId))throw new Error('Verified native administrator required');
 if(typeof path!=='string'||!new RegExp('^/course/'+record.id+'/[a-f0-9]{64}$').test(path))throw new Error('Unknown immutable native path');
 if(!info||['name','title','timezone'].some(k=>typeof info[k]!=='string'||!info[k].trim())||info.title.length>75)throw new Error('Native course metadata required');
 new Intl.DateTimeFormat('en',{timeZone:info.timezone});
 const institutionId=await resolveInstitution(catalog,record.institution,native);
 return native.withLock('deployment-course:'+path,async()=>{
  const existing=await native.selectOptionalCourseByPath(path);
  if(existing) {
   if(existing.institution_id!==institutionId)throw new Error('Native course institution mismatch; migration is not supported');
   return existing;
  }
  // Readonly immutable snapshots have no native repository-sync operation.
  // Native insertCourse records the authenticated actor in its audit trail.
  return await native.insertCourse({institution_id:institutionId,short_name:info.name,title:info.title,display_timezone:info.timezone,path,repository:null,branch:'master',authn_user_id:actorId});
 });
}
